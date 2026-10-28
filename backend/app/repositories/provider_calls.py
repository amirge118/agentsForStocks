"""ProviderCallRepository — the per-day call count of a metered provider."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.provider_call import ProviderCall


class ProviderCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def increment(self, provider: str, day: date) -> int:
        """Count one call and return the day's total — atomic, so every process agrees."""
        dialect = self._session.get_bind().dialect.name
        insert = sqlite.insert if dialect == "sqlite" else postgresql.insert
        stmt = insert(ProviderCall).values(provider=provider, day=day, calls=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider", "day"], set_={"calls": ProviderCall.calls + 1}
        ).returning(ProviderCall.calls)
        return int((await self._session.execute(stmt)).scalar_one())

    async def count(self, provider: str, day: date) -> int:
        stmt = select(ProviderCall.calls).where(
            ProviderCall.provider == provider, ProviderCall.day == day
        )
        return int((await self._session.execute(stmt)).scalar_one_or_none() or 0)


class StoredCallCounter:
    """CallCounter for DailyCallBudget backed by short-lived sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], provider: str) -> None:
        self._session_factory = session_factory
        self._provider = provider

    async def increment(self, day: date) -> int:
        async with self._session_factory() as session:
            total = await ProviderCallRepository(session).increment(self._provider, day)
            await session.commit()
            return total
