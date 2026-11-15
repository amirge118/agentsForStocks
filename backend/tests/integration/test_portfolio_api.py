"""/api/v1/portfolio end to end: real container, routers, repositories and SQLite."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.api.v1.endpoints import portfolio as portfolio_api
from app.container import build_container
from app.core.config import Settings
from app.main import app
from app.providers.yfinance import Quote
from app.repositories.agent_results import AgentResultRepository
from app.repositories.daily_closes import DailyCloseRepository
from app.repositories.watchlist import WatchlistRepository


@pytest.fixture
async def api(concurrent_session_factory) -> AsyncIterator[httpx.AsyncClient]:
    container = build_container(Settings(openviking_enabled=False), concurrent_session_factory)

    async def known(symbol: str) -> bool | None:
        return {"ZZZZ": False, "OFFLINE": None}.get(symbol, True)

    container.ticker_exists = known
    live: dict[str, Quote] = {}

    async def quotes(symbols: Sequence[str], ttl: float | None) -> dict[str, Quote]:
        return {s: live[s] for s in symbols if s in live}

    container.quotes = quotes
    container.live = live  # type: ignore[attr-defined]  # the tests set today's quotes
    history: list[tuple[list[str], date, date]] = []

    async def daily_closes(
        symbols: Sequence[str], start: date, end: date
    ) -> dict[str, tuple[tuple[date, float], ...]]:
        """Every weekday in [start, end): SPY 400, MSFT 500, each +1 a session."""
        history.append((list(symbols), start, end))
        days = [start + timedelta(n) for n in range((end - start).days)]
        sessions = [d for d in days if d.weekday() < 5]
        base = {"SPY": 400.0, "MSFT": 500.0}
        return {
            s: tuple((d, base[s] + i) for i, d in enumerate(sessions)) for s in symbols if s in base
        }

    container.daily_closes = daily_closes
    container.history = history  # type: ignore[attr-defined]  # the fetches made
    app.state.container = container
    async with concurrent_session_factory() as session:
        await WatchlistRepository(session).add("MSFT")
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await container.aclose()


def _tx(kind: str, day: str = "2026-11-02", **fields: object) -> dict:
    return {"trade_date": day, "kind": kind, **fields}


@pytest.mark.integration
async def test_a_ledger_adds_up_to_cash_holdings_and_pl(api: httpx.AsyncClient) -> None:
    empty = (await api.get("/api/v1/portfolio")).json()
    assert empty["cash"] == 0 and empty["positions"] == []

    for body in (
        _tx("DEPOSIT", amount=10000, note="opening cash"),
        _tx("TRANSFER_IN", symbol="goog", shares=20, price=150),
        _tx("BUY", "2026-11-03", symbol="MSFT", shares=10, price="520.5", fee=1),
        _tx("SELL", "2026-11-04", symbol="MSFT", shares=4, price=560, fee=1),
        _tx("DIVIDEND", "2026-11-04", symbol="GOOG", amount="4.2"),
    ):
        resp = await api.post("/api/v1/portfolio/transactions", json=body)
        assert resp.status_code == 201, resp.text

    portfolio = (await api.get("/api/v1/portfolio")).json()
    assert portfolio["cash"] == pytest.approx(10000 - 5206 + 2239 + 4.2)
    assert portfolio["deposited"] == 10000 and portfolio["transferred_in"] == 3000
    assert portfolio["fees"] == 2 and portfolio["dividends"] == pytest.approx(4.2)
    by_symbol = {p["symbol"]: p for p in portfolio["positions"]}
    assert by_symbol["MSFT"]["shares"] == 6
    assert by_symbol["MSFT"]["avg_cost"] == pytest.approx(520.6)
    assert by_symbol["MSFT"]["realised_pnl"] == pytest.approx(4 * 560 - 1 - 4 * 520.6)
    # Largest value first; without any price (no quotes here) they are listed by symbol
    assert [p["symbol"] for p in portfolio["positions"]] == ["GOOG", "MSFT"]
    assert (
        portfolio["unpriced"] == ["GOOG", "MSFT"] and portfolio["total_value"] == portfolio["cash"]
    )

    listed = (await api.get("/api/v1/portfolio/transactions")).json()
    # Newest first: the latest day, then the latest recorded that day
    assert [t["kind"] for t in listed][:2] == ["DIVIDEND", "SELL"]
    assert listed[-1]["note"] == "opening cash"

    # A symbol brought in joins the watchlist, so the agents analyse it
    assert [i["symbol"] for i in (await api.get("/api/v1/watchlist")).json()] == ["MSFT", "GOOG"]


@pytest.mark.integration
async def test_writes_that_break_the_ledger_are_refused_with_the_reason(
    api: httpx.AsyncClient,
) -> None:
    post = lambda body: api.post("/api/v1/portfolio/transactions", json=body)  # noqa: E731

    no_cash = await post(_tx("BUY", symbol="MSFT", shares=1, price=500))
    assert no_cash.status_code == 422 and "record a deposit first" in no_cash.json()["detail"]
    deposit = (await post(_tx("DEPOSIT", amount=1000))).json()
    oversold = await post(_tx("SELL", symbol="MSFT", shares=1, price=500))
    assert oversold.status_code == 422 and "only 0 held" in oversold.json()["detail"]
    unknown = await post(_tx("BUY", symbol="zzzz", shares=1, price=1))
    assert unknown.status_code == 422 and "no market data" in unknown.json()["detail"]

    # Malformed: caught by the schema before the ledger
    assert (
        await post(_tx("BUY", "2999-01-01", symbol="MSFT", shares=1, price=1))
    ).status_code == 422
    assert (await post(_tx("BUY", symbol="MSFT", shares=-1, price=1))).status_code == 422
    assert (await post(_tx("BUY", symbol="MSFT", shares="0.1234567", price=1))).status_code == 422
    assert (await post(_tx("BUY", symbol="BAD$", shares=1, price=1))).status_code == 422
    assert (await post(_tx("DEPOSIT", amount=1, symbol="MSFT"))).status_code == 422
    assert (await post(_tx("GIFT", amount=1))).status_code == 422

    buy = (await post(_tx("BUY", "2026-11-03", symbol="MSFT", shares=2, price=400))).json()
    gone = await api.delete(f"/api/v1/portfolio/transactions/{deposit['id']}")
    assert gone.status_code == 422 and "a later entry depends on this one" in gone.json()["detail"]
    shrink = await api.put(
        f"/api/v1/portfolio/transactions/{deposit['id']}", json=_tx("DEPOSIT", amount=100)
    )
    assert shrink.status_code == 422

    fixed = await api.put(
        f"/api/v1/portfolio/transactions/{buy['id']}",
        json=_tx("BUY", "2026-11-03", symbol="MSFT", shares=2, price=450, note="real price"),
    )
    assert fixed.status_code == 200 and fixed.json()["price"] == 450
    assert (await api.delete(f"/api/v1/portfolio/transactions/{buy['id']}")).status_code == 204
    assert (await api.delete(f"/api/v1/portfolio/transactions/{buy['id']}")).status_code == 404
    assert (
        await api.put("/api/v1/portfolio/transactions/999", json=_tx("DEPOSIT", amount=1))
    ).status_code == 404
    assert (await api.get("/api/v1/portfolio")).json()["cash"] == 1000


def _quote(symbol: str, price: float, previous: float) -> Quote:
    closes = ((date(2026, 11, 12), previous), (date(2026, 11, 13), price))
    return Quote(symbol, price, previous, date(2026, 11, 13), closes)


@pytest.mark.integration
async def test_the_portfolio_at_todays_prices_and_a_stored_close_when_none_comes(
    api: httpx.AsyncClient,
) -> None:
    for body in (
        _tx("DEPOSIT", amount=10000),
        _tx("BUY", symbol="MSFT", shares=10, price=500),
        _tx("TRANSFER_IN", symbol="GOOG", shares=20, price=150),
        _tx("TRANSFER_IN", symbol="NEWCO", shares=5, price=10),
    ):
        assert (await api.post("/api/v1/portfolio/transactions", json=body)).status_code == 201
    live = app.state.container.live
    live["MSFT"] = _quote("MSFT", 520, 510)
    live["GOOG"] = _quote("GOOG", 160, 158)

    portfolio = (await api.get("/api/v1/portfolio")).json()
    assert portfolio["cash"] == 5000
    assert portfolio["holdings_value"] == 5200 + 3200
    assert portfolio["total_value"] == 13400
    assert portfolio["unrealised_pnl"] == 200 + 200
    assert portfolio["day_change"] == 100 + 40
    assert portfolio["day_change_pct"] == pytest.approx(140 / (13400 - 140) * 100)
    assert portfolio["unpriced"] == ["NEWCO"]  # no quote, no stored close: not valued at 0
    by_symbol = {p["symbol"]: p for p in portfolio["positions"]}
    msft = by_symbol["MSFT"]
    assert (msft["price"], msft["value"], msft["unrealised_pct"]) == (520, 5200, 4.0)
    assert msft["weight"] == pytest.approx(5200 / 13400 * 100)
    assert msft["price_as_of"] == "2026-11-13" and msft["price_stale"] is False
    assert by_symbol["NEWCO"]["value"] is None and by_symbol["NEWCO"]["price"] is None

    # The finished sessions were stored; with the source down, the last one is used
    live.clear()
    stale = {p["symbol"]: p for p in (await api.get("/api/v1/portfolio")).json()["positions"]}
    assert stale["MSFT"]["price"] == 520 and stale["MSFT"]["price_stale"] is True
    assert stale["MSFT"]["day_change"] is None
    async with app.state.container.session_factory() as session:
        stored = await DailyCloseRepository(session).latest(["MSFT", "GOOG"])
    assert {s: day for s, (day, _) in stored.items()} == {
        "MSFT": date(2026, 11, 13),
        "GOOG": date(2026, 11, 13),
    }


@pytest.mark.integration
async def test_performance_is_empty_without_entries(api: httpx.AsyncClient) -> None:
    perf = (await api.get("/api/v1/portfolio/performance")).json()
    assert perf["benchmark"] == "SPY" and perf["since"] is None
    assert perf["series"] == [] and perf["gainers"] == [] and perf["total_return_pct"] is None
    assert app.state.container.history == []


@pytest.mark.integration
async def test_performance_fetches_the_missing_closes_once_and_beats_spy_or_not(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2026, 11, 10)  # a Tuesday, after the close
    monkeypatch.setattr(portfolio_api, "market_today", lambda: today)
    monkeypatch.setattr(portfolio_api, "utcnow", lambda: datetime(2026, 11, 10, 23, tzinfo=UTC))
    for body in (_tx("DEPOSIT", amount=10000), _tx("BUY", symbol="MSFT", shares=10, price=500)):
        assert (await api.post("/api/v1/portfolio/transactions", json=body)).status_code == 201
    live = app.state.container.live
    live["MSFT"] = Quote("MSFT", 520, 510, today, ())
    live["SPY"] = Quote("SPY", 420, 410, today, ())

    perf = (await api.get("/api/v1/portfolio/performance")).json()
    # One request, from a week before the first entry, for the symbol and the benchmark
    assert app.state.container.history == [(["MSFT", "SPY"], date(2026, 10, 26), today)]
    days = [p["day"] for p in perf["series"]]
    assert days[0] == "2026-11-02" and days[-1] == "2026-11-10" and len(days) == 7
    # Monday's close: MSFT 505 (the 6th weekday from Oct 26), so 5000 cash + 5050
    assert perf["series"][0]["value"] == 10050 and perf["series"][0]["flow"] == 10000
    assert perf["series"][-1]["value"] == 10200  # today's live 520
    assert perf["total_return_pct"] == pytest.approx(2.0)
    assert perf["benchmark_return_pct"] == pytest.approx((420 / 404 - 1) * 100)  # from Oct 30
    # The week, from Friday Nov 6 (MSFT 509)
    assert perf["week_start"] == "2026-11-06"
    assert perf["week_change"] == pytest.approx(110)
    assert perf["week_change_pct"] == pytest.approx((10200 / 10090 - 1) * 100)
    assert perf["gainers"] == [
        {"symbol": "MSFT", "change": 110, "change_pct": pytest.approx((520 / 509 - 1) * 100)}
    ]
    assert perf["losers"] == []

    # The closes are stored now: the next view fetches nothing
    await api.get("/api/v1/portfolio/performance")
    assert len(app.state.container.history) == 1


async def _store(agent: str, symbol: str, day: date, result: dict) -> None:
    async with app.state.container.session_factory() as session:
        await AgentResultRepository(session).upsert(
            agent_type=agent, symbol=symbol, run_date=day, run_id="r", result=result
        )
        await session.commit()


@pytest.mark.integration
async def test_exposure_sectors_risk_and_the_agents_calls(api: httpx.AsyncClient) -> None:
    for body in (
        _tx("DEPOSIT", amount=10000),
        _tx("BUY", symbol="MSFT", shares=10, price=500),
        _tx("TRANSFER_IN", symbol="SPY", shares=4, price=500),
    ):
        assert (await api.post("/api/v1/portfolio/transactions", json=body)).status_code == 201
    live = app.state.container.live
    live["MSFT"] = _quote("MSFT", 520, 510)
    live["SPY"] = _quote("SPY", 500, 500)
    earlier, later = date(2026, 11, 12), date(2026, 11, 13)
    await _store("broad_analysis", "MSFT", later, {"sector": "Technology"})
    await _store("risk", "MSFT", later, {"beta": 1.2})
    await _store("recommendation", "MSFT", earlier, {"action": "HOLD"})
    await _store("recommendation", "MSFT", later, {"action": "BUY"})
    await _store("technicals", "SPY", later, {"signal": "neutral"})  # no company agents: a fund

    targets = [{"sector": " Technology ", "target_pct": 40}, {"sector": "Energy", "target_pct": 5}]
    saved = await api.put("/api/v1/portfolio/sector-targets", json=targets)
    assert saved.status_code == 200
    assert [t["sector"] for t in saved.json()] == ["Energy", "Technology"]

    out = (await api.get("/api/v1/portfolio/exposure")).json()
    total = 5000 + 5200 + 2000
    sectors = {s["sector"]: s for s in out["sectors"]}
    assert [s["sector"] for s in out["sectors"]] == ["Technology", "Fund", "Energy", "Cash"]
    assert sectors["Technology"]["weight"] == pytest.approx(5200 / total * 100)
    assert sectors["Technology"]["drift"] == pytest.approx(5200 / total * 100 - 40)
    assert sectors["Energy"]["weight"] == 0 and sectors["Energy"]["drift"] == -5
    risk = out["risk"]
    assert risk["largest_symbol"] == "MSFT" and risk["beta"] == pytest.approx(1.2)
    assert risk["beta_coverage"] == pytest.approx(5200 / 7200 * 100)  # SPY has no beta
    assert [(a["action"], a["symbols"]) for a in out["actions"]] == [
        ("BUY", ["MSFT"]),
        ("Not analysed yet", ["SPY"]),
    ]
    assert out["changed"] == [
        {"symbol": "MSFT", "action": "BUY", "previous": "HOLD", "run_date": "2026-11-13"}
    ]


@pytest.mark.integration
async def test_sector_targets_are_checked(api: httpx.AsyncClient) -> None:
    put = "/api/v1/portfolio/sector-targets"
    assert (await api.put(put, json=[{"sector": "A", "target_pct": 101}])).status_code == 422
    assert (await api.put(put, json=[{"sector": "  ", "target_pct": 5}])).status_code == 422
    twice = [{"sector": "A", "target_pct": 5}, {"sector": "A", "target_pct": 6}]
    assert (await api.put(put, json=twice)).status_code == 422
    many = [{"sector": f"S{i}", "target_pct": 1} for i in range(51)]
    assert (await api.put(put, json=many)).status_code == 422
    assert (await api.put(put, json=[])).json() == []
    empty = (await api.get("/api/v1/portfolio/exposure")).json()
    assert [s["sector"] for s in empty["sectors"]] == ["Cash"] and empty["actions"] == []
