"""DecisionOutcomeRepository — pending rows for every judged day, and the rows still to settle."""

from collections.abc import Iterable, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_result import AgentResult
from app.models.decision_outcome import DecisionOutcome


class DecisionOutcomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def seed_pending(
        self,
        horizons: Sequence[int],
        benchmark: str,
        symbols: Iterable[str] | None = None,
    ) -> int:
        """
        Add a pending row per horizon for every (symbol, run_date) in agent_results
        that has none yet — so the first pass backfills all history. Returns the
        number of rows added; existing rows are never touched.
        """
        decisions = select(AgentResult.symbol, AgentResult.run_date).distinct()
        existing = select(
            DecisionOutcome.symbol, DecisionOutcome.decision_date, DecisionOutcome.horizon_days
        )
        if symbols is not None:
            wanted = list(symbols)
            decisions = decisions.where(AgentResult.symbol.in_(wanted))
            existing = existing.where(DecisionOutcome.symbol.in_(wanted))
        have = {tuple(row) for row in (await self._session.execute(existing)).all()}
        rows = [
            {
                "id": str(uuid4()),
                "symbol": symbol,
                "decision_date": run_date,
                "horizon_days": horizon,
                "benchmark": benchmark,
                "status": "pending",
                "attempts": 0,
            }
            for symbol, run_date in (await self._session.execute(decisions)).all()
            for horizon in horizons
            if (symbol, run_date, horizon) not in have
        ]
        if not rows:
            return 0
        # A concurrent pass may have added some of them: those are skipped, not duplicated
        dialect = self._session.get_bind().dialect.name
        insert = sqlite.insert if dialect == "sqlite" else postgresql.insert
        await self._session.execute(
            insert(DecisionOutcome)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["symbol", "decision_date", "horizon_days"])
        )
        return len(rows)

    async def pending(self, symbols: Iterable[str] | None = None) -> list[DecisionOutcome]:
        """Rows still to settle, by symbol and oldest decision first."""
        stmt = select(DecisionOutcome).where(DecisionOutcome.status == "pending")
        if symbols is not None:
            stmt = stmt.where(DecisionOutcome.symbol.in_(list(symbols)))
        stmt = stmt.order_by(
            DecisionOutcome.symbol, DecisionOutcome.decision_date, DecisionOutcome.horizon_days
        )
        return list((await self._session.execute(stmt)).scalars().all())
