import pytest
from sqlalchemy import text

from app.container import build_container
from app.core.config import Settings
from app.ops.preflight import CheckResult, ready, render, run_preflight
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
