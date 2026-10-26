import pytest
from sqlalchemy import text

from app.container import build_container
from app.core.config import Settings
from app.llm.chain import FallbackChain, parse_chain
from app.llm.client import LLMError
from app.llm.quota import ProviderQuota, QuotaLimits
from app.llm.router import LLMRouter
from app.ops.preflight import CheckResult, ready, render, run_preflight
from app.schemas.signals import LLMSignal
from tests.factories import FakeEdgar, FakeFmp, FakeLLM, FakeYFinance, make_context

KEY = "x" * 40


@pytest.fixture
async def migrated(session_factory):
    async with session_factory() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await session.execute(text("INSERT INTO alembic_version VALUES ('0002')"))
        await session.commit()
    return session_factory


async def _preflight(session_factory, settings: Settings, **ctx) -> dict[str, CheckResult]:
    container = build_container(settings, session_factory)
    container.agent_context = make_context(**ctx)
    container.llm = ctx.get("llm") or FakeLLM()
    try:
        results = await run_preflight(settings, container, session_factory)
    finally:
        await container.aclose()
    return {r.name: r for r in results}


def _settings(**overrides) -> Settings:
    base = {"openviking_enabled": False, "anthropic_api_key": KEY, "fmp_api_key": KEY}
    return Settings(**{**base, **overrides})


@pytest.mark.unit
async def test_everything_ok(migrated) -> None:
    results = await _preflight(migrated, _settings())
    assert {n: r.status for n, r in results.items()} == {
        "database": "ok",
        "claude": "ok",
        "fmp": "ok",
        "yahoo_finance": "ok",
        "sec_edgar": "ok",
        "openviking": "ok",
    }
    assert results["database"].detail == "connected, migration 0002"
    assert "Apple" in results["fmp"].detail
    assert ready(list(results.values()))
    assert "READY for a real pipeline run" in render(list(results.values()))


@pytest.mark.unit
async def test_missing_keys_are_reported_not_called(migrated) -> None:
    llm = FakeLLM()
    results = await _preflight(migrated, _settings(anthropic_api_key="", fmp_api_key=""), llm=llm)
    assert results["claude"].status == "missing"
    assert results["fmp"].status == "missing"
    assert llm.calls == []
    assert not ready(list(results.values()))


@pytest.mark.unit
async def test_failures_are_explained(session_factory) -> None:
    class BlockedYahoo(FakeYFinance):
        async def get_info(self, symbol: str) -> dict:
            raise ConnectionError("CONNECT tunnel failed, response 403")

    class EmptyEdgar(FakeEdgar):
        async def get_business_section(self, symbol: str) -> str:
            return ""  # EdgarClient returns "" when SEC refuses the request

    results = await _preflight(
        session_factory,  # no alembic_version table → migrations not applied
        _settings(),
        yfinance=BlockedYahoo(),
        edgar=EmptyEdgar(),
        fmp=FakeFmp(profile={}),
        llm=FakeLLM(fail=True),
    )
    failed = {n for n, r in results.items() if r.status == "failed"}
    assert failed == {"database", "yahoo_finance", "sec_edgar", "fmp", "claude"}
    assert "403" in results["yahoo_finance"].detail
    assert "User-Agent" in results["sec_edgar"].detail
    text_ = render(list(results.values()))
    assert "[FAIL] yahoo_finance" in text_
    assert "NOT READY" in text_


@pytest.mark.unit
async def test_yahoo_without_price_fails(migrated) -> None:
    results = await _preflight(
        migrated, _settings(), yfinance=FakeYFinance(info={"symbol": "AAPL"})
    )
    assert results["yahoo_finance"].status == "failed"


@pytest.mark.unit
async def test_knowledge_is_optional(migrated) -> None:
    results = await _preflight(migrated, _settings(openviking_enabled=True))
    knowledge = results["openviking"]
    assert knowledge.required is False
    # unreachable OpenViking does not block readiness
    assert ready([r for r in results.values()]) or knowledge.status != "ok"
    assert ready([r for r in results.values() if r.name != "openviking"])


@pytest.mark.unit
def test_explain_shows_the_root_cause() -> None:
    from app.ops.preflight import _explain
    from app.providers.errors import ProviderError

    try:
        try:
            raise ConnectionError("Tunnel connection failed: 403 Forbidden")
        except ConnectionError as inner:
            raise ProviderError("yfinance.info(AAPL) failed after 3 attempts") from inner
    except ProviderError as exc:
        text_ = _explain(exc)
    assert text_.startswith("ProviderError: yfinance.info(AAPL) failed after 3 attempts")
    assert text_.endswith("← ConnectionError: Tunnel connection failed: 403 Forbidden")


class FakeCompat:
    """An OpenAI-compatible provider as the preflight sees it."""

    structured_mode = "json_object"

    def __init__(self, model: str, offered: list[str] | None = None, fail: bool = False) -> None:
        self.default_model = model
        self.offered = [model] if offered is None else offered
        self.fail = fail
        self.quota = ProviderQuota("free", QuotaLimits(rpm=10, rpd=1000))
        self.calls = 0

    async def list_models(self) -> list[str]:
        return self.offered

    async def generate(self, **kwargs) -> LLMSignal:
        self.calls += 1
        if self.fail:
            raise LLMError("HTTP 401")
        return LLMSignal(signal="neutral", confidence=0, reasoning="ok")

    async def aclose(self) -> None:
        return None


def _router(**free: FakeCompat) -> LLMRouter:
    providers = {"anthropic": FakeLLM(), **free}
    chain = FallbackChain(parse_chain("gemini,groq,anthropic"), providers)
    return LLMRouter({**providers, "chain": chain}, default_provider="chain")


@pytest.mark.unit
async def test_free_providers_and_the_chain_are_checked(migrated) -> None:
    gemini, groq = FakeCompat("gemini-flash"), FakeCompat("gpt-oss-120b", fail=True)
    settings = _settings(llm_provider="chain", anthropic_api_key="")
    results = await _preflight(migrated, settings, llm=_router(gemini=gemini, groq=groq))

    assert results["llm:gemini"].status == "ok"
    assert results["llm:gemini"].detail == (
        "gemini-flash json_object output ok (signal=neutral); free tier 10 rpm, 1000 rpd"
    )
    assert results["llm:groq"].status == "failed" and "HTTP 401" in results["llm:groq"].detail
    assert not results["llm:groq"].required  # the chain survives one bad provider
    assert results["claude"].status == "missing" and not results["claude"].required
    chain = results["llm:chain"]
    assert (chain.status, chain.required) == ("ok", True)
    assert chain.detail == "gemini → groq → anthropic (1 of 3 healthy)"
    assert ready(list(results.values()))


@pytest.mark.unit
async def test_an_unknown_model_id_is_reported_with_what_is_offered(migrated) -> None:
    gemini = FakeCompat("gemini-9-flash", offered=["gemini-3.5-flash-lite", "gemini-3-flash"])
    settings = _settings(llm_provider="gemini")
    results = await _preflight(migrated, settings, llm=_router(gemini=gemini))
    check = results["llm:gemini"]
    assert (check.status, check.required) == ("failed", True)
    assert "'gemini-9-flash' is not offered" in check.detail
    assert "gemini-3.5-flash-lite" in check.detail
    assert gemini.calls == 0  # no completion is spent on a model that doesn't exist
    assert not ready(list(results.values()))


@pytest.mark.unit
async def test_a_chain_with_no_healthy_step_is_not_ready(migrated) -> None:
    settings = _settings(llm_provider="chain", anthropic_api_key="")
    broken = await _preflight(migrated, settings, llm=_router(gemini=FakeCompat("g", fail=True)))
    assert broken["llm:chain"].status == "failed"
    assert not ready(list(broken.values()))

    empty = LLMRouter({"anthropic": FakeLLM(), "chain": FallbackChain([], {})}, "chain")
    nothing = await _preflight(migrated, settings, llm=empty)
    assert nothing["llm:chain"].status == "missing"


@pytest.mark.unit
async def test_an_unconfigured_default_provider_is_missing(migrated) -> None:
    results = await _preflight(migrated, _settings(llm_provider="alt"))
    assert results["llm:alt"].status == "missing"
    assert "LLM_ALT_BASE_URL" in results["llm:alt"].detail
    assert not ready(list(results.values()))
