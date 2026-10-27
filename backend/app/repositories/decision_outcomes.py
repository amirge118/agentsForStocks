"""DecisionOutcomeRepository — pending rows for every judged day, the rows still to settle,
and settled outcomes joined to the calls they score."""

from collections.abc import Iterable, Sequence
from datetime import date
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.outcomes import SettledCall
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

    async def settled_calls(
        self, symbol: str, *, agent: str, horizon: int, before: date, limit: int
    ) -> list[SettledCall]:
        """
        `agent`'s calls on `symbol` whose `horizon` outcome was known before `before`
        (exit session earlier than it), newest first — point-in-time for a run on `before`.
        """
        rows = await self.scored_calls(
            horizon, agent=agent, symbol=symbol, before=before, limit=limit
        )
        return [call for _, call in rows]

    async def scored_calls(
        self,
        horizon: int,
        *,
        agent: str | None = None,
        exclude_agents: Iterable[str] = (),
        symbol: str | None = None,
        since: date | None = None,
        before: date | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, SettledCall]]:
        """(agent, call) for every stored call with a settled `horizon` outcome, newest first."""
        stmt = (
            select(DecisionOutcome, AgentResult.agent_type, AgentResult.result_json)
            .join(
                AgentResult,
                (AgentResult.symbol == DecisionOutcome.symbol)
                & (AgentResult.run_date == DecisionOutcome.decision_date),
            )
            .where(
                DecisionOutcome.horizon_days == horizon,
                DecisionOutcome.status == "settled",
            )
            .order_by(DecisionOutcome.decision_date.desc(), AgentResult.agent_type)
        )
        if agent is not None:
            stmt = stmt.where(AgentResult.agent_type == agent)
        excluded = list(exclude_agents)
        if excluded:
            stmt = stmt.where(AgentResult.agent_type.not_in(excluded))
        if symbol is not None:
            stmt = stmt.where(DecisionOutcome.symbol == symbol)
        if since is not None:
            stmt = stmt.where(DecisionOutcome.decision_date >= since)
        if before is not None:
            stmt = stmt.where(DecisionOutcome.exit_date < before)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [
            (agent_type, _settled_call(o, result))
            for o, agent_type, result in (await self._session.execute(stmt)).all()
        ]

    async def status_counts(self, horizon: int, symbol: str | None = None) -> dict[str, int]:
        """{status: rows} at one horizon — how many outcomes are still pending or unavailable."""
        stmt = (
            select(DecisionOutcome.status, func.count())
            .where(DecisionOutcome.horizon_days == horizon)
            .group_by(DecisionOutcome.status)
        )
        if symbol is not None:
            stmt = stmt.where(DecisionOutcome.symbol == symbol)
        return {status: count for status, count in (await self._session.execute(stmt)).all()}


def _settled_call(o: DecisionOutcome, result: dict) -> SettledCall:
    return SettledCall(
        symbol=o.symbol,
        decision_date=o.decision_date,
        exit_date=o.exit_date,
        horizon=o.horizon_days,
        benchmark=o.benchmark,
        signal=str(result.get("signal", "neutral")),
        confidence=float(result.get("confidence", 0.0)),
        reasoning=str(result.get("reasoning", "")),
        raw_return=o.raw_return,
        alpha=o.alpha,
    )
