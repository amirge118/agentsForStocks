"""/api/v1/portfolio end to end: real container, routers, repositories and SQLite."""

from collections.abc import AsyncIterator

import httpx
import pytest

from app.container import build_container
from app.core.config import Settings
from app.main import app
from app.repositories.watchlist import WatchlistRepository


@pytest.fixture
async def api(concurrent_session_factory) -> AsyncIterator[httpx.AsyncClient]:
    container = build_container(Settings(openviking_enabled=False), concurrent_session_factory)

    async def known(symbol: str) -> bool | None:
        return {"ZZZZ": False, "OFFLINE": None}.get(symbol, True)

    container.ticker_exists = known
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
    # Largest cost first: MSFT 6 x 520.6 = 3,123.6, GOOG 3,000
    assert [p["symbol"] for p in portfolio["positions"]] == ["MSFT", "GOOG"]

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
