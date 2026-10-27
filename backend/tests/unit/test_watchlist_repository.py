import pytest

from app.repositories.watchlist import (
    MAX_SYMBOLS,
    DuplicateSymbolError,
    WatchlistFullError,
    WatchlistRepository,
)


@pytest.mark.unit
async def test_add_appends_in_order(db_session) -> None:
    repo = WatchlistRepository(db_session)
    assert await repo.symbols() == []
    for symbol in ("MSFT", "AAPL", "BRK.B"):
        await repo.add(symbol)
    await db_session.commit()

    items = await repo.items()
    assert [(i.symbol, i.position) for i in items] == [("MSFT", 0), ("AAPL", 1), ("BRK.B", 2)]
    assert all(i.added_at is not None for i in items)


@pytest.mark.unit
async def test_duplicate_and_full_are_rejected(db_session) -> None:
    repo = WatchlistRepository(db_session)
    await repo.add("AAPL")
    with pytest.raises(DuplicateSymbolError, match="already on the watchlist"):
        await repo.add("AAPL")

    for i in range(MAX_SYMBOLS - 1):
        await repo.add(f"S{i}")
    with pytest.raises(WatchlistFullError, match=str(MAX_SYMBOLS)):
        await repo.add("ONEMORE")


@pytest.mark.unit
async def test_remove_then_add_goes_to_the_end(db_session) -> None:
    repo = WatchlistRepository(db_session)
    for symbol in ("AAPL", "MSFT", "NVDA"):
        await repo.add(symbol)

    assert await repo.remove("AAPL") is True
    assert await repo.remove("AAPL") is False
    await repo.add("AAPL")
    assert await repo.symbols() == ["MSFT", "NVDA", "AAPL"]


@pytest.mark.unit
async def test_reorder_needs_exactly_the_current_set(db_session) -> None:
    repo = WatchlistRepository(db_session)
    for symbol in ("AAPL", "MSFT", "NVDA"):
        await repo.add(symbol)

    reordered = await repo.reorder(["NVDA", "AAPL", "MSFT"])
    assert [(i.symbol, i.position) for i in reordered] == [("NVDA", 0), ("AAPL", 1), ("MSFT", 2)]
    assert await repo.symbols() == ["NVDA", "AAPL", "MSFT"]

    for bad in (["NVDA", "AAPL"], ["NVDA", "AAPL", "MSFT", "TSLA"], ["NVDA", "NVDA", "AAPL"]):
        with pytest.raises(ValueError, match="exactly once"):
            await repo.reorder(bad)
    assert await repo.symbols() == ["NVDA", "AAPL", "MSFT"]
