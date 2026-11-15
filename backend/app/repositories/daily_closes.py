"""DailyCloseRepository — finished sessions' closes, written once, read after."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_close import DailyClose


class DailyCloseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, symbol: str, closes: Iterable[tuple[date, float]]) -> int:
        """Store the closes not stored yet; returns how many were new."""
        rows = dict(closes)
        if not rows:
            return 0
        stmt = select(DailyClose.day).where(
            DailyClose.symbol == symbol, DailyClose.day.in_(list(rows))
        )
        known = set((await self._session.execute(stmt)).scalars())
        new = [day for day in rows if day not in known]
        for day in new:
            self._session.add(DailyClose(symbol=symbol, day=day, close=_money(rows[day])))
        await self._session.flush()
        return len(new)

    async def latest(self, symbols: Iterable[str]) -> dict[str, tuple[date, Decimal]]:
        """Each symbol's most recent stored close (symbols with none are left out)."""
        wanted = list(set(symbols))
        if not wanted:
            return {}
        last = (
            select(DailyClose.symbol, func.max(DailyClose.day).label("day"))
            .where(DailyClose.symbol.in_(wanted))
            .group_by(DailyClose.symbol)
            .subquery()
        )
        stmt = select(DailyClose).join(
            last, (DailyClose.symbol == last.c.symbol) & (DailyClose.day == last.c.day)
        )
        rows = (await self._session.execute(stmt)).scalars()
        return {row.symbol: (row.day, row.close) for row in rows}


def _money(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))
