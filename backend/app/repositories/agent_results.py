"""AgentResultRepository — reads and idempotent writes for the agent_results table."""

from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.agent_result import AgentResult


class AgentResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, agent_type: str, symbol: str, run_date: date) -> bool:
        stmt = select(AgentResult.id).where(
            AgentResult.agent_type == agent_type,
            AgentResult.symbol == symbol,
            AgentResult.run_date == run_date,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def upsert(
        self,
        *,
        agent_type: str,
        symbol: str,
        run_date: date,
        run_id: str,
        result: dict[str, Any],
    ) -> None:
        """Insert or replace the (agent_type, symbol, run_date) row — re-runs never duplicate."""
        # Both Postgres (prod) and SQLite (tests) support ON CONFLICT DO UPDATE
        dialect = self._session.get_bind().dialect.name
        insert = sqlite.insert if dialect == "sqlite" else postgresql.insert
        now = utcnow()
        stmt = (
            insert(AgentResult)
            .values(
                agent_type=agent_type,
                symbol=symbol,
                run_date=run_date,
                run_id=run_id,
                result_json=result,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["agent_type", "symbol", "run_date"],
                set_={"result_json": result, "run_id": run_id, "updated_at": now},
            )
        )
        await self._session.execute(stmt)

    async def get_for_date(
        self, symbol: str, run_date: date, agent_types: Iterable[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """{agent_type: result_json} for one symbol on one market date."""
        stmt = select(AgentResult).where(
            AgentResult.symbol == symbol, AgentResult.run_date == run_date
        )
        if agent_types is not None:
            stmt = stmt.where(AgentResult.agent_type.in_(list(agent_types)))
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.agent_type: row.result_json for row in rows}

    async def latest_per_symbol(
        self, agent_type: str, symbols: Iterable[str]
    ) -> dict[str, AgentResult]:
        """{symbol: most recent row of agent_type} — one query for a whole watchlist."""
        latest = (
            select(AgentResult.symbol, func.max(AgentResult.run_date).label("run_date"))
            .where(AgentResult.agent_type == agent_type, AgentResult.symbol.in_(list(symbols)))
            .group_by(AgentResult.symbol)
            .subquery()
        )
        stmt = (
            select(AgentResult)
            .join(
                latest,
                (AgentResult.symbol == latest.c.symbol)
                & (AgentResult.run_date == latest.c.run_date),
            )
            .where(AgentResult.agent_type == agent_type)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.symbol: row for row in rows}

    async def list_for_symbol(
        self,
        symbol: str,
        *,
        agent_type: str | None = None,
        run_date: date | None = None,
        limit: int = 50,
    ) -> list[AgentResult]:
        """Newest first, optionally narrowed to one agent and/or one market date."""
        stmt = select(AgentResult).where(AgentResult.symbol == symbol)
        if agent_type is not None:
            stmt = stmt.where(AgentResult.agent_type == agent_type)
        if run_date is not None:
            stmt = stmt.where(AgentResult.run_date == run_date)
        stmt = stmt.order_by(AgentResult.run_date.desc(), AgentResult.agent_type).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def recent(
        self,
        agent_type: str,
        *,
        until: date,
        symbol: str | None = None,
        exclude_symbol: str | None = None,
        limit: int = 20,
    ) -> list[AgentResult]:
        """Rows of one agent dated on or before `until`, newest first."""
        stmt = select(AgentResult).where(
            AgentResult.agent_type == agent_type, AgentResult.run_date <= until
        )
        if symbol is not None:
            stmt = stmt.where(AgentResult.symbol == symbol)
        if exclude_symbol is not None:
            stmt = stmt.where(AgentResult.symbol != exclude_symbol)
        stmt = stmt.order_by(AgentResult.run_date.desc(), AgentResult.symbol).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())
