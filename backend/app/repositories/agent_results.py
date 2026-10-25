"""AgentResultRepository — reads and idempotent writes for the agent_results table."""

from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import select
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

    async def latest_for_symbol(
        self, symbol: str, agent_type: str | None = None, limit: int = 50
    ) -> list[AgentResult]:
        """Most recent results first."""
        stmt = select(AgentResult).where(AgentResult.symbol == symbol)
        if agent_type is not None:
            stmt = stmt.where(AgentResult.agent_type == agent_type)
        stmt = stmt.order_by(AgentResult.run_date.desc(), AgentResult.agent_type).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())
