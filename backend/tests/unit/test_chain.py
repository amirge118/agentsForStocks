import json
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.agents.market_scanner import MarketScannerAgent
from app.agents.runner import AgentRunner
from app.knowledge.store import NullKnowledgeStore
from app.llm.chain import ChainStep, FallbackChain, parse_chain
from app.llm.client import LLMError
from app.llm.mcp import McpServer
from app.llm.openai_compat import OpenAICompatibleClient, QuotaExhaustedError
from app.llm.quota import ProviderQuota, QuotaLimits
from app.llm.recording import DbLLMCallRecorder
from app.llm.router import LLMRouter
from app.models.agent_run import AgentRun
from app.models.llm_call import LLMCall
from app.providers.retry import RetryPolicy
from app.schemas.signals import LLMSignal
from tests.factories import FakeLLM, make_context

RUN_DATE = date(2026, 10, 26)
FAST = RetryPolicy(max_attempts=2, timeout_seconds=5, base_backoff_seconds=0)
SCAN = {
    "signal": "bullish",
    "confidence": 61,
    "reasoning": "Above its 20-day average on rising volume",
    "observations": ["price above SMA20"],
    "risk_level": "low",
}


class Step:
    """A provider that fails with `error` (or answers) and records what it was asked."""

    def __init__(self, error: Exception | None = None, default_model: str = "m") -> None:
        self.error = error
        self.default_model = default_model
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> LLMSignal:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return LLMSignal(signal="bullish", confidence=60, reasoning="ok")


async def _ask(chain: FallbackChain, **kwargs) -> LLMSignal:
    return await chain.generate(system="s", prompt="p", schema=LLMSignal, **kwargs)


@pytest.mark.unit
def test_parse_chain() -> None:
    assert parse_chain(" gemini, groq:qwen/qwen3-32b ,,anthropic:claude-haiku-5-5") == [
        ChainStep("gemini"),
        ChainStep("groq", "qwen/qwen3-32b"),
        ChainStep("anthropic", "claude-haiku-5-5"),
    ]
    assert ChainStep("groq", "x").label == "groq:x" and ChainStep("gemini").label == "gemini"


@pytest.mark.unit
async def test_falls_through_quota_and_errors_to_the_first_answer() -> None:
    gemini = Step(QuotaExhaustedError("gemini quota has no room"))
    groq = Step(LLMError("reply did not match LLMSignal"))
    cerebras = Step()
    chain = FallbackChain(
        parse_chain("gemini,groq,cerebras,anthropic"),
        {"gemini": gemini, "groq": groq, "cerebras": cerebras, "anthropic": Step()},
    )
    assert (await _ask(chain)).signal == "bullish"
    assert (len(gemini.calls), len(groq.calls), len(cerebras.calls)) == (1, 1, 1)


@pytest.mark.unit
async def test_every_step_failing_is_one_llm_error_naming_each() -> None:
    chain = FallbackChain(
        parse_chain("gemini,groq"),
        {"gemini": Step(LLMError("HTTP 503")), "groq": Step(QuotaExhaustedError("no room"))},
    )
    with pytest.raises(LLMError, match=r"gemini: HTTP 503; groq: no room"):
        await _ask(chain)


@pytest.mark.unit
async def test_unconfigured_steps_are_dropped_and_an_empty_chain_errors() -> None:
    gemini = Step(default_model="gemini-3.5-flash-lite")
    chain = FallbackChain(parse_chain("cerebras,gemini,chain"), {"gemini": gemini})
    assert [s.label for s in chain.steps] == ["gemini"]
    assert chain.default_model == "gemini-3.5-flash-lite"

    empty = FallbackChain(parse_chain("cerebras"), {})
    assert empty.default_model == ""
    with pytest.raises(LLMError, match="no provider"):
        await _ask(empty)


@pytest.mark.unit
async def test_a_caller_bug_is_not_swallowed() -> None:
    later = Step()
    chain = FallbackChain(
        parse_chain("gemini,groq"), {"gemini": Step(ValueError("bad schema")), "groq": later}
    )
    with pytest.raises(ValueError, match="bad schema"):
        await _ask(chain)
    assert later.calls == []


@pytest.mark.unit
async def test_model_choice_step_model_wins_and_hints_only_reach_claude() -> None:
    gemini, claude = Step(LLMError("down")), Step()
    chain = FallbackChain(parse_chain("gemini,anthropic"), {"gemini": gemini, "anthropic": claude})
    await _ask(chain, model="claude-sonnet-5-5")
    assert gemini.calls[0]["model"] is None  # its own default, not a Claude model id
    assert claude.calls[0]["model"] == "claude-sonnet-5-5"

    pinned = Step()
    chain = FallbackChain(parse_chain("anthropic:claude-haiku-5-5"), {"anthropic": pinned})
    await _ask(chain, model="claude-sonnet-5-5")
    assert pinned.calls[0]["model"] == "claude-haiku-5-5"


@pytest.mark.unit
async def test_mcp_calls_only_go_to_claude() -> None:
    gemini, claude = Step(), Step()
    chain = FallbackChain(parse_chain("gemini,anthropic"), {"gemini": gemini, "anthropic": claude})
    server = McpServer(name="factset", url="https://mcp.example.com")
    await _ask(chain, mcp_servers=[server])
    assert gemini.calls == [] and claude.calls[0]["mcp_servers"] == [server]


def _free(name: str, handler, quota: ProviderQuota | None, recorder, mode="json_schema"):
    return OpenAICompatibleClient(
        base_url=f"https://{name}.example.com/v1",
        api_key="k",
        default_model=f"{name}-model",
        name=name,
        structured_mode=mode,
        quota=quota,
        recorder=recorder,
        transport=httpx.MockTransport(handler),
        retry_policy=FAST,
    )


def _completion(body: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "choices": [{"message": {"content": json.dumps(body)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 80},
        },
    )


@pytest.mark.unit
async def test_agent_run_end_to_end_rate_limited_free_tier_falls_to_the_next(
    session_factory, db_session
) -> None:
    """Gemini answers 429, Groq answers in JSON mode: the run succeeds, both calls are logged."""
    sent: dict[str, list[dict]] = {"gemini": [], "groq": []}

    def gemini(request: httpx.Request) -> httpx.Response:
        sent["gemini"].append(json.loads(request.content))
        return httpx.Response(429, headers={"retry-after": "30"}, json={"error": "quota"})

    def groq(request: httpx.Request) -> httpx.Response:
        sent["groq"].append(json.loads(request.content))
        return _completion(SCAN)

    recorder = DbLLMCallRecorder(session_factory)
    gemini_quota = ProviderQuota("gemini", QuotaLimits(rpm=10, rpd=1000))
    providers = {
        "gemini": _free("gemini", gemini, gemini_quota, recorder),
        "groq": _free("groq", groq, ProviderQuota("groq", QuotaLimits()), recorder, "json_object"),
    }
    chain = FallbackChain(parse_chain("gemini,groq,anthropic"), providers)
    router = LLMRouter({"anthropic": FakeLLM(), **providers, "chain": chain}, "chain")
    agent = MarketScannerAgent(make_context(llm=router))

    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)

    assert outcome.result is not None and outcome.result.signal == "bullish"
    assert len(sent["gemini"]) == 1  # a 429 is not retried on a free tier
    groq_body = sent["groq"][0]
    assert groq_body["response_format"] == {"type": "json_object"}
    assert "matches this JSON schema" in groq_body["messages"][0]["content"]
    calls = (await db_session.execute(select(LLMCall).order_by(LLMCall.created_at))).scalars()
    assert [(c.provider, c.status) for c in calls] == [("gemini", "error"), ("groq", "ok")]
    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert (run.llm_calls, run.llm_fallbacks) == (2, 0)

    # Gemini is cooling down: the next call skips it without sending anything
    await router.generate(system="s", prompt="p", schema=LLMSignal)
    assert len(sent["gemini"]) == 1 and len(sent["groq"]) == 2
    await router.aclose()


@pytest.mark.unit
async def test_agent_falls_back_to_its_rule_based_signal_when_the_chain_fails(
    session_factory, db_session
) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    providers = {"gemini": _free("gemini", down, None, DbLLMCallRecorder(session_factory))}
    chain = FallbackChain(parse_chain("gemini"), providers)
    router = LLMRouter({"anthropic": FakeLLM(), **providers, "chain": chain}, "chain")
    agent = MarketScannerAgent(make_context(llm=router))

    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)

    assert outcome.result is not None and outcome.result.signal == "neutral"
    assert "LLM unavailable" in outcome.result.reasoning
    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert run.llm_fallbacks == 1
    await router.aclose()
