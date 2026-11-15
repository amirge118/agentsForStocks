"""SectorTargetRepository — the sector targets, replaced as a whole set."""

from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sector_target import SectorTarget


class SectorTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> dict[str, Decimal]:
        rows = (await self._session.execute(select(SectorTarget))).scalars()
        return {row.sector: row.target_pct for row in rows}

    async def replace(self, targets: Mapping[str, Decimal]) -> dict[str, Decimal]:
        """The new set: sectors left out lose their target."""
        await self._session.execute(delete(SectorTarget))
        for sector, pct in targets.items():
            self._session.add(SectorTarget(sector=sector, target_pct=pct))
        await self._session.flush()
        return dict(targets)
