"""Track-record endpoints end to end: real container, routers, repositories and SQLite."""

from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest

from app.container import build_container
from app.core.config import Settings
from app.main import app
from app.models.decision_outcome import DecisionOutcome
from app.repositories.agent_results import AgentResultRepository

DAYS = (date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3))


@pytest.fixture
async def api(concurrent_session_factory) -> AsyncIterator[httpx.AsyncClient]:
    container = build_container(Settings(openviking_enabled=False), concurrent_session_factory)
    app.state.container = container
    async with concurrent_session_factory() as session:
        results = AgentResultRepository(session)
        # AAPL: bullish +2% alpha (right), bearish +1% (wrong), then a still-pending day
        for day, signal, confidence, alpha in (
            (DAYS[0], "bullish", 85.0, 0.02),
            (DAYS[1], "bearish", 55.0, 0.01),
        ):
            for agent in ("recommendation", "moat", "outcome_review"):
                await results.upsert(
                    agent_type=agent,
                    symbol="AAPL",
                    run_date=day,
                    run_id="r",
                    result={"signal": signal, "confidence": confidence},
                )
            session.add(
                DecisionOutcome(
                    symbol="AAPL",
                    decision_date=day,
                    horizon_days=20,
                    benchmark="SPY",
                    status="settled",
                    exit_date=date(2026, 10, 1),
                    raw_return=alpha + 0.005,
                    alpha=alpha,
                )
            )
        session.add(
            DecisionOutcome(
                symbol="AAPL",
                decision_date=DAYS[2],
                horizon_days=20,
                benchmark="SPY",
                status="pending",
            )
        )
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await container.aclose()


@pytest.mark.integration
async def test_track_record_per_agent(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/outcomes/track-record")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["horizon"], body["settled"], body["pending"], body["unavailable"]) == (
        20,
        2,
        1,
        0,
    )
    # outcome_review judges past calls, not the stock: not scored
    assert [a["agent"] for a in body["agents"]] == ["recommendation", "moat"]
    rec = body["agents"][0]
    assert rec["overall"] == {
        "calls": 2,
        "hits": 1,
        "hit_rate": 0.5,
        "mean_alpha_captured": pytest.approx((0.02 - 0.01) / 2),
    }
    assert [(g["key"], g["hits"]) for g in rec["by_signal"]] == [("bullish", 1), ("bearish", 0)]
    assert [g["key"] for g in rec["by_confidence"]] == ["40-60", "80-100"]

    later = await api.get("/api/v1/outcomes/track-record", params={"since": "2026-09-02"})
    assert later.json()["agents"][0]["overall"]["calls"] == 1
    empty = await api.get("/api/v1/outcomes/track-record", params={"horizon": 5})
    assert empty.json()["agents"] == []
    bad = await api.get("/api/v1/outcomes/track-record", params={"horizon": 7})
    assert bad.status_code == 422


@pytest.mark.integration
async def test_symbol_outcomes(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/symbols/aapl/outcomes")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["symbol"], body["horizon"], body["pending"]) == ("AAPL", 20, 1)
    assert body["overall"]["calls"] == 2 and body["overall"]["hits"] == 1
    first = body["calls"][0]  # newest first
    assert first["decision_date"] == "2026-09-02"
    assert (first["signal"], first["hit"], first["benchmark"]) == ("bearish", False, "SPY")
    assert first["benchmark_return"] == pytest.approx(0.005)
    assert len((await api.get("/api/v1/symbols/AAPL/outcomes?limit=1")).json()["calls"]) == 1
    nothing = (await api.get("/api/v1/symbols/MSFT/outcomes")).json()
    assert nothing["overall"] == {
        "calls": 0,
        "hits": 0,
        "hit_rate": None,
        "mean_alpha_captured": None,
    }
    assert (await api.get("/api/v1/symbols/AAPL/outcomes?horizon=3")).status_code == 422
