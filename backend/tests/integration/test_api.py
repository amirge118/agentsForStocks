"""/api/v1 end to end: real container, routers, repositories and SQLite — fake providers/LLM."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest

from app.agents.runner import SessionResultsReader
from app.container import build_container
from app.core.config import Settings
from app.main import app
from app.pipeline.launcher import PipelineLauncher
from app.pipeline.orchestrator import PipelineOrchestrator
from app.repositories.agent_results import AgentResultRepository
from tests.factories import FakeLLM, make_context

D1 = date(2026, 10, 22)
D2 = date(2026, 10, 23)


def _recommendation(action: str, signal: str, score: float) -> dict:
    return {
        "signal": signal,
        "confidence": 66.0,
        "reasoning": "r",
        "summary": f"{action} summary",
        "action": action,
        "weighted_score": score,
        "agents_available": 8,
        "agents_missing": [],
        "risk_override_applied": False,
        "compliance": {"status": "pass", "findings": [], "original_reasoning": None},
        "disclaimer": "Not investment advice.",
        "agent_breakdown": [
            {
                "agent": "moat",
                "signal": signal,
                "confidence": 80.0,
                "weight": 15.0,
                "contribution": 12.0,
                "reasoning": "brand",
            }
        ],
    }


@pytest.fixture
async def api(concurrent_session_factory) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(openviking_enabled=False, watchlist="AAPL,MSFT")
    container = build_container(settings, concurrent_session_factory)
    # Swap the launcher for one whose agents use fake providers and a fake LLM
    ctx = make_context(llm=FakeLLM(), results=SessionResultsReader(concurrent_session_factory))
    orchestrator = PipelineOrchestrator(
        container.runner,
        container.registry,
        build_agent=lambda name: container.registry.get(name).agent_cls(ctx),
    )
    container.launcher = PipelineLauncher(orchestrator, container.registry)
    app.state.container = container

    async with concurrent_session_factory() as session:
        repo = AgentResultRepository(session)
        await repo.upsert(
            agent_type="recommendation",
            symbol="AAPL",
            run_date=D1,
            run_id="old",
            result=_recommendation("HOLD", "neutral", 3.0),
        )
        await repo.upsert(
            agent_type="recommendation",
            symbol="AAPL",
            run_date=D2,
            run_id="new",
            result=_recommendation("BUY", "bullish", 42.0),
        )
        await repo.upsert(
            agent_type="moat", symbol="AAPL", run_date=D2, run_id="m", result={"signal": "bullish"}
        )
        await session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await container.aclose()


@pytest.mark.integration
async def test_list_agents_in_execution_order(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 13
    assert agents[-1]["name"] == "recommendation"
    assert sum(a["recommendation_weight"] for a in agents) == 100


@pytest.mark.integration
async def test_symbols_overview_uses_latest_recommendation(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/symbols")
    assert resp.status_code == 200
    by_symbol = {s["symbol"]: s["recommendation"] for s in resp.json()}
    assert list(by_symbol) == ["AAPL", "MSFT"]
    assert by_symbol["AAPL"]["action"] == "BUY"
    assert by_symbol["AAPL"]["run_date"] == "2026-10-23"
    assert by_symbol["AAPL"]["agent_breakdown"][0]["agent"] == "moat"
    assert by_symbol["MSFT"] is None


@pytest.mark.integration
async def test_symbol_recommendation_and_errors(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/symbols/aapl/recommendation")
    assert resp.status_code == 200
    assert resp.json()["weighted_score"] == 42.0
    assert resp.json()["compliance"]["status"] == "pass"
    assert resp.json()["disclaimer"] == "Not investment advice."
    assert (await api.get("/api/v1/symbols/MSFT/recommendation")).status_code == 404
    assert (await api.get("/api/v1/symbols/BAD;SYM/recommendation")).status_code == 422


@pytest.mark.integration
async def test_symbol_results_filters(api: httpx.AsyncClient) -> None:
    all_rows = (await api.get("/api/v1/symbols/AAPL/results")).json()
    assert [(r["agent_type"], r["run_date"]) for r in all_rows] == [
        ("moat", "2026-10-23"),
        ("recommendation", "2026-10-23"),
        ("recommendation", "2026-10-22"),
    ]
    moat = (await api.get("/api/v1/symbols/AAPL/results", params={"agent": "moat"})).json()
    assert moat[0]["result"] == {"signal": "bullish"}
    dated = await api.get("/api/v1/symbols/AAPL/results", params={"run_date": "2026-10-22"})
    assert [r["run_id"] for r in dated.json()] == ["old"]
    unknown = await api.get("/api/v1/symbols/AAPL/results", params={"agent": "nope"})
    assert unknown.status_code == 422
    assert (await api.get("/api/v1/symbols/AAPL/results", params={"limit": 0})).status_code == 422


@pytest.mark.integration
async def test_trigger_pipeline_then_inspect_runs(api: httpx.AsyncClient) -> None:
    resp = await api.post(
        "/api/v1/pipeline/runs", json={"symbols": ["msft"], "agents": ["technicals"]}
    )
    assert resp.status_code == 202
    accepted = resp.json()
    assert accepted["symbols"] == ["MSFT"]
    assert accepted["agents"] == ["technicals"]

    for _ in range(100):  # the run happens in the background
        runs = (
            await api.get("/api/v1/runs", params={"pipeline_run_id": accepted["pipeline_run_id"]})
        ).json()
        if runs:
            break
        await asyncio.sleep(0.02)
    assert [(r["agent_type"], r["symbol"], r["status"]) for r in runs] == [
        ("technicals", "MSFT", "completed")
    ]
    filtered = await api.get("/api/v1/runs", params={"symbol": "msft", "status": "completed"})
    assert len(filtered.json()) == 1
    assert (await api.get("/api/v1/runs", params={"status": "weird"})).status_code == 422
    assert (await api.get("/api/v1/runs", params={"symbol": "x;y"})).status_code == 422


@pytest.mark.integration
async def test_trigger_pipeline_rejects_bad_input(api: httpx.AsyncClient) -> None:
    bad_agent = await api.post("/api/v1/pipeline/runs", json={"agents": ["nope"]})
    assert bad_agent.status_code == 422
    bad_symbol = await api.post("/api/v1/pipeline/runs", json={"symbols": ["../etc"]})
    assert bad_symbol.status_code == 422


@pytest.mark.integration
async def test_trigger_defaults_to_watchlist_and_all_agents(api: httpx.AsyncClient) -> None:
    resp = await api.post("/api/v1/pipeline/runs", json={})
    assert resp.status_code == 202
    body = resp.json()
    assert body["symbols"] == ["AAPL", "MSFT"]
    assert body["agents"][-1] == "recommendation"
    assert app.state.container.launcher.active == 1


@pytest.mark.integration
async def test_llm_ledger_endpoints(api: httpx.AsyncClient, concurrent_session_factory) -> None:
    from app.core.clock import utcnow
    from app.llm.pricing import TokenUsage
    from app.llm.recording import DbLLMCallRecorder, LLMCallRecord

    recorder = DbLLMCallRecorder(concurrent_session_factory)
    for call_id, agent, run_id, provider in (
        ("c1", "moat", "r1", "anthropic"),
        ("c2", "moat", "r1", "anthropic"),
        ("c3", "risk", "r2", "gemini"),
    ):
        await recorder.record(
            LLMCallRecord(
                call_id=call_id,
                created_at=utcnow(),
                model="claude-haiku-4-5",
                prompt_name=agent,
                prompt_version="v1",
                status="ok",
                latency_ms=100,
                usage=TokenUsage(input_tokens=1000, output_tokens=100),
                cost_usd=0.0015,
                run_id=run_id,
                agent=agent,
                symbol="AAPL",
                provider=provider,
                system_prompt="You are a moat analyst.",
                prompt="Symbol: AAPL",
                response='{"signal":"bullish"}',
            )
        )

    usage = (await api.get("/api/v1/llm/usage", params={"days": 7})).json()
    assert usage["group_by"] == "agent"
    assert [(r["key"], r["calls"]) for r in usage["rows"]] == [("moat", 2), ("risk", 1)]
    assert usage["total_calls"] == 3
    assert usage["total_input_tokens"] == 3000
    assert usage["total_cost_usd"] == pytest.approx(0.0045)
    by_model = (await api.get("/api/v1/llm/usage", params={"group_by": "model"})).json()
    assert [r["key"] for r in by_model["rows"]] == ["claude-haiku-4-5"]
    by_provider = (await api.get("/api/v1/llm/usage", params={"group_by": "provider"})).json()
    assert sorted((r["key"], r["calls"]) for r in by_provider["rows"]) == [
        ("anthropic", 2),
        ("gemini", 1),
    ]
    bad = await api.get("/api/v1/llm/usage", params={"group_by": "nope"})
    assert bad.status_code == 422

    calls = (await api.get("/api/v1/runs/r1/llm-calls")).json()
    assert [c["call_id"] for c in calls] == ["c1", "c2"]  # in call order
    assert calls[0]["system_prompt"] == "You are a moat analyst."
    assert calls[0]["provider"] == "anthropic"
    listed = (await api.get("/api/v1/llm/calls", params={"agent": "risk"})).json()
    assert [c["call_id"] for c in listed] == ["c3"]


@pytest.mark.integration
async def test_llm_providers_show_chain_order_limits_and_use_today(
    api: httpx.AsyncClient, concurrent_session_factory
) -> None:
    from app.container import build_llm_router
    from app.core.clock import utcnow
    from app.llm.pricing import TokenUsage
    from app.llm.recording import DbLLMCallRecorder, LLMCallRecord, NullRecorder

    container = app.state.container
    container.llm = build_llm_router(
        Settings(gemini_api_key="g", groq_api_key="q", llm_provider="chain"), NullRecorder()
    )
    recorder = DbLLMCallRecorder(concurrent_session_factory)
    for call_id in ("g1", "g2"):
        await recorder.record(
            LLMCallRecord(
                call_id=call_id,
                created_at=utcnow(),
                model="gemini-3.5-flash-lite",
                prompt_name="moat",
                prompt_version="v1",
                status="ok",
                latency_ms=100,
                usage=TokenUsage(input_tokens=900, output_tokens=100),
                cost_usd=0.0,
                provider="gemini",
            )
        )

    providers = {p["name"]: p for p in (await api.get("/api/v1/llm/providers")).json()}
    assert list(providers) == ["anthropic", "gemini", "groq"]
    gemini = providers["gemini"]
    assert (gemini["chain_position"], gemini["rpd"], gemini["rpm"]) == (1, 1000, 10)
    assert (gemini["day_requests"], gemini["day_tokens"]) == (2, 2000)
    assert gemini["structured_mode"] == "json_schema"
    assert gemini["day_start"].endswith(("-07:00", "-08:00"))  # midnight Pacific
    assert providers["groq"]["chain_position"] == 2
    # No ANTHROPIC_API_KEY: Claude is routable but not in the chain, and has no free-tier limits
    claude = providers["anthropic"]
    assert (claude["chain_position"], claude["rpd"], claude["structured_mode"]) == (
        None,
        None,
        None,
    )
    await container.llm.aclose()


@pytest.mark.integration
async def test_agents_show_their_effective_profile(api: httpx.AsyncClient) -> None:
    agents = {a["name"]: a for a in (await api.get("/api/v1/agents")).json()}
    assert agents["moat"]["profile"] == {
        "provider": "anthropic",
        "model": None,
        "skills": [],
        "use_llm": True,
    }
