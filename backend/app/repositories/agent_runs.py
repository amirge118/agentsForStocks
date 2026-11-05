"""AgentRunRepository — the execution audit trail."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, run: AgentRun) -> None:
        self._session.add(run)

    async def list(
        self,
        *,
        symbol: str | None = None,
        run_date: date | None = None,
        status: str | None = None,
        pipeline_run_id: str | None = None,
        agent: str | None = None,
        since: date | None = None,
        hide_skipped: bool = False,
        limit: int = 100,
    ) -> list[AgentRun]:
        """Newest first. `since` keeps runs dated on or after that market day."""
        stmt = select(AgentRun)
        if agent is not None:
            stmt = stmt.where(AgentRun.agent_type == agent)
        if since is not None:
            stmt = stmt.where(AgentRun.run_date >= since)
        if symbol is not None:
            stmt = stmt.where(AgentRun.symbol == symbol)
        if run_date is not None:
            stmt = stmt.where(AgentRun.run_date == run_date)
        if status is not None:
            stmt = stmt.where(AgentRun.status == status)
        if hide_skipped:
            stmt = stmt.where(AgentRun.status != "skipped")
        if pipeline_run_id is not None:
            stmt = stmt.where(AgentRun.pipeline_run_id == pipeline_run_id)
        stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())
