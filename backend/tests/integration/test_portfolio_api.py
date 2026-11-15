"""/api/v1/portfolio end to end: real container, routers, repositories and SQLite."""

from collections.abc import AsyncIterator, Sequence
from datetime import date

import httpx
import pytest

from app.container import build_container
from app.core.config import Settings
from app.main import app
from app.providers.yfinance import Quote
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
