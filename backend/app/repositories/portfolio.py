"""
PortfolioRepository — the ledger's rows. Every write is checked by replaying the whole
ledger with the change (app/domain/portfolio.py), so an entry that would ever sell shares
not held, or spend cash not there, is refused with LedgerError and nothing is written.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.portfolio import Entry, Ledger, replay
from app.models.portfolio_transaction import PortfolioTransaction


class TransactionNotFoundError(LookupError):
    pass


class PortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(self) -> list[PortfolioTransaction]:
        """Newest first."""
        stmt = select(PortfolioTransaction).order_by(
            PortfolioTransaction.trade_date.desc(), PortfolioTransaction.id.desc()
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def ledger(self) -> Ledger:
        return replay(to_entry(row) for row in await self.rows())

    async def add(self, entry: Entry, note: str | None = None) -> PortfolioTransaction:
        rows = await self.rows()
        replay([*(to_entry(r) for r in rows), entry])
        row = PortfolioTransaction(note=note)
        _fill(row, entry)
        self._session.add(row)
        await self._session.flush()
        return row

    async def update(
        self, transaction_id: int, entry: Entry, note: str | None = None
    ) -> PortfolioTransaction:
        rows = await self.rows()
        row = _find(rows, transaction_id)
        changed = Entry(**{**vars(entry), "id": transaction_id})
        replay(changed if r.id == transaction_id else to_entry(r) for r in rows)
        _fill(row, entry)
        row.note = note
        await self._session.flush()
        return row

    async def delete(self, transaction_id: int) -> None:
        rows = await self.rows()
        row = _find(rows, transaction_id)
        replay(to_entry(r) for r in rows if r.id != transaction_id)
        await self._session.delete(row)
        await self._session.flush()


def to_entry(row: PortfolioTransaction) -> Entry:
    return Entry(
        trade_date=row.trade_date,
        kind=row.kind,  # type: ignore[arg-type]  # written from a validated Kind
        symbol=row.symbol,
        shares=row.shares,
        price=row.price,
        fee=row.fee,
        amount=row.amount,
        id=row.id,
    )


def _find(rows: list[PortfolioTransaction], transaction_id: int) -> PortfolioTransaction:
    for row in rows:
        if row.id == transaction_id:
            return row
    raise TransactionNotFoundError(f"no transaction {transaction_id}")


def _fill(row: PortfolioTransaction, entry: Entry) -> None:
    row.trade_date = entry.trade_date
    row.kind = entry.kind
    row.symbol = entry.symbol
    row.shares = entry.shares
    row.price = entry.price
    row.fee = entry.fee
    row.amount = entry.amount
