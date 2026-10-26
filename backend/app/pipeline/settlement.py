"""
OutcomeSettler — scores stored decisions against realised prices. No LLM.

Each pass:
  1. seeds a pending row per horizon for every (symbol, day) in agent_results
     that has none — so the first pass backfills all history;
  2. fetches each pending symbol's closes (one call per symbol) and the
     benchmark's (one call per benchmark), up to the day before `as_of`;
  3. scores every pending row whose window has fully traded and commits per
     symbol, so an interrupted pass keeps what it finished.

Idempotent: a settled row is never touched again, and a window that has not
traded yet stays pending for the next pass. A row whose window should long have
traded but has no prices (delisted, renamed) is counted once per pass and marked
unavailable after `max_attempts` passes.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import pandas as pd
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import market_today, utcnow
from app.domain.outcomes import HORIZONS, daily_closes, score, window_end
from app.models.decision_outcome import DecisionOutcome
from app.observability import metrics
from app.providers.errors import ProviderError
from app.repositories.decision_outcomes import DecisionOutcomeRepository

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

MAX_ATTEMPTS = 5
# The benchmark needs a close on or before each entry, which follows the decision day
_BENCHMARK_LEAD = timedelta(days=7)


class PriceSource(Protocol):
    async def get_closes(self, symbol: str, start: date, end: date) -> pd.Series: ...


@dataclass
class SettlementReport:
    as_of: date
    seeded: int = 0
    settled: int = 0
    pending: int = 0
    unavailable: int = 0
    failed_symbols: list[str] = field(default_factory=list)

    def render(self) -> str:
        line = (
            f"Outcomes as of {self.as_of}: {self.settled} settled, {self.pending} pending, "
            f"{self.unavailable} unavailable ({self.seeded} new)"
        )
        if self.failed_symbols:
            line += f"; prices unavailable for {', '.join(self.failed_symbols)}"
        return line


class OutcomeSettler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prices: PriceSource,
        *,
        benchmark: str = "SPY",
        horizons: Sequence[int] = HORIZONS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._session_factory = session_factory
        self._prices = prices
        self._benchmark = benchmark
        self._horizons = tuple(horizons)
        self._max_attempts = max_attempts

    async def settle(
        self, *, as_of: date | None = None, symbols: Sequence[str] | None = None
    ) -> SettlementReport:
        """Settle what has traded by the close before `as_of` (default: today's market date)."""
        as_of = as_of or market_today()
        report = SettlementReport(as_of=as_of)
        with tracer.start_as_current_span("outcomes.settle", attributes={"as_of": str(as_of)}):
            async with self._session_factory() as session:
                repo = DecisionOutcomeRepository(session)
                report.seeded = await repo.seed_pending(self._horizons, self._benchmark, symbols)
                await session.commit()
                # A decision dated as_of or later has no session after it yet
                rows = [r for r in await repo.pending(symbols) if r.decision_date < as_of]
                if rows:
                    await self._settle_rows(session, rows, as_of, report)
        logger.info(
            "Outcome settlement finished",
            extra={
                "seeded": report.seeded,
                "settled": report.settled,
                "pending": report.pending,
                "unavailable": report.unavailable,
                "failed_symbols": report.failed_symbols,
            },
        )
        return report

    async def _settle_rows(
        self,
        session: AsyncSession,
        rows: list[DecisionOutcome],
        as_of: date,
        report: SettlementReport,
    ) -> None:
        by_symbol: dict[str, list[DecisionOutcome]] = defaultdict(list)
        for row in rows:
            by_symbol[row.symbol].append(row)

        start = min(r.decision_date for r in rows) - _BENCHMARK_LEAD
        benchmarks: dict[str, pd.Series] = {}
        for name in sorted({r.benchmark for r in rows}):
            try:
                benchmarks[name] = await self._closes(name, start, as_of)
            except ProviderError as exc:
                # Not the stocks' fault: leave everything pending, count no attempts
                logger.warning(
                    "Benchmark prices unavailable, outcomes stay pending",
                    extra={"benchmark": name, "error": str(exc)},
                )
                report.pending += len(rows)
                return

        for symbol, symbol_rows in by_symbol.items():
            try:
                closes = await self._closes(
                    symbol, min(r.decision_date for r in symbol_rows), as_of
                )
            except ProviderError as exc:
                logger.warning(
                    "Prices unavailable for settlement", extra={"symbol": symbol, "error": str(exc)}
                )
                report.failed_symbols.append(symbol)
                closes = pd.Series(dtype=float)
            for row in symbol_rows:
                self._apply(row, closes, benchmarks[row.benchmark], as_of, report)
            await session.commit()

    async def _closes(self, symbol: str, start: date, as_of: date) -> pd.Series:
        """Closes from `start` through the day before `as_of`: today's bar may still move."""
        closes = daily_closes(await self._prices.get_closes(symbol, start, as_of))
        return closes[closes.index < pd.Timestamp(as_of)]

    def _apply(
        self,
        row: DecisionOutcome,
        closes: pd.Series,
        benchmark: pd.Series,
        as_of: date,
        report: SettlementReport,
    ) -> None:
        scored = score(closes, benchmark, row.decision_date, row.horizon_days)
        if scored.outcome is not None:
            o = scored.outcome
            row.entry_date, row.exit_date = o.entry_date, o.exit_date
            row.entry_price, row.exit_price = o.entry_price, o.exit_price
            row.raw_return, row.benchmark_return, row.alpha = (
                o.raw_return,
                o.benchmark_return,
                o.alpha,
            )
            row.status = "settled"
            row.settled_at = utcnow()
            report.settled += 1
            metrics.outcomes_settled.add(1, {"status": "settled", "horizon": row.horizon_days})
            return
        if scored.missing == "stock" and as_of > window_end(row.decision_date, row.horizon_days):
            row.attempts += 1
            if row.attempts >= self._max_attempts:
                row.status = "unavailable"
                report.unavailable += 1
                metrics.outcomes_settled.add(
                    1, {"status": "unavailable", "horizon": row.horizon_days}
                )
                logger.warning(
                    "Outcome unavailable: the window traded long ago but has no prices",
                    extra={
                        "symbol": row.symbol,
                        "decision_date": str(row.decision_date),
                        "horizon_days": row.horizon_days,
                    },
                )
                return
        report.pending += 1
