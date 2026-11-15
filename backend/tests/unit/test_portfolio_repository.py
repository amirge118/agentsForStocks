from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.portfolio import Entry, LedgerError
from app.repositories.portfolio import PortfolioRepository, TransactionNotFoundError

DAY = date(2026, 11, 2)
NEXT = date(2026, 11, 3)


@pytest.mark.unit
async def test_rows_round_trip_exactly_and_come_back_newest_first(db_session) -> None:
    repo = PortfolioRepository(db_session)
    await repo.add(Entry(DAY, "DEPOSIT", amount=D("1000.25")), note="opening cash")
    await repo.add(Entry(NEXT, "BUY", "MSFT", D("0.5"), D("520.123456"), D("1")))
    await db_session.commit()

    rows = await repo.rows()
    assert [r.kind for r in rows] == ["BUY", "DEPOSIT"]
    assert rows[0].price == D("520.123456") and rows[1].note == "opening cash"
    ledger = await repo.ledger()
    assert ledger.cash == D("1000.25") - D("0.5") * D("520.123456") - D("1")


@pytest.mark.unit
async def test_a_refused_write_changes_nothing(db_session) -> None:
    repo = PortfolioRepository(db_session)
    deposit = await repo.add(Entry(DAY, "DEPOSIT", amount=D("500")))
    buy = await repo.add(Entry(NEXT, "BUY", "MSFT", D("1"), D("400")))
    await db_session.commit()

    with pytest.raises(LedgerError):
        await repo.add(Entry(NEXT, "BUY", "MSFT", D("1"), D("400")))
    with pytest.raises(LedgerError):  # the buy needs that cash
        await repo.delete(deposit.id)
    with pytest.raises(LedgerError):
        await repo.update(deposit.id, Entry(DAY, "DEPOSIT", amount=D("100")))
    assert len(await repo.rows()) == 2

    await repo.update(buy.id, Entry(NEXT, "BUY", "MSFT", D("1"), D("450")), note="fixed price")
    await repo.delete(buy.id)
    await repo.delete(deposit.id)
    assert await repo.rows() == []
    with pytest.raises(TransactionNotFoundError):
        await repo.delete(deposit.id)
