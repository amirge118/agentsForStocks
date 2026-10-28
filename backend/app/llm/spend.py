"""
DailySpend — a cap on what paid model calls may cost in one market day.

The free providers can't cost money; Claude (and a priced "alt" provider) can, and
a loop, a retry storm or a misconfigured chain would only show on the invoice.
Before each paid request the client asks check(): once the day's spend reaches
LLM_DAILY_BUDGET_USD the request is refused with QuotaExhaustedError, so the
chain moves on or the agent falls back (and its result is marked needs_review).
Every recorded call adds its cost. The day's spend is seeded from the llm_calls
ledger the first time it is needed, so a restart doesn't forget it. 0 = no cap.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time

from app.core.clock import MARKET_TZ, market_today
from app.llm.errors import QuotaExhaustedError
from app.llm.pricing import Price
from app.observability import metrics

logger = logging.getLogger(__name__)

# since → the cost of every call recorded since then (USD)
SpendLoader = Callable[[datetime], Awaitable[float]]
_WARN_RATIO = 0.8


def is_paid(price: Price | None) -> bool:
    """A model that costs money; unknown models count as paid (we can't prove otherwise)."""
    return price is None or price.input > 0 or price.output > 0


class DailySpend:
    def __init__(
        self,
        limit_usd: float,
        load_spent: SpendLoader | None = None,
        today: Callable[[], date] = market_today,
    ) -> None:
        self.limit_usd = limit_usd
        self._load = load_spent
        self._today = today
        self._day: date | None = None
        self.spent = 0.0
        self._warned = False
        self._refused = False

    @property
    def enabled(self) -> bool:
        return self.limit_usd > 0

    async def check(self, provider: str, model: str) -> None:
        """Raise QuotaExhaustedError when the day's budget is spent."""
        if not self.enabled:
            return
        await self._roll_day()
        if self.spent < self.limit_usd:
            return
        metrics.llm_budget_refusals.add(1, {"provider": provider})
        if not self._refused:  # once a day: the alert, not one line per call
            self._refused = True
            logger.error(
                "Daily LLM budget spent — paid calls refused until tomorrow",
                extra={"spent_usd": round(self.spent, 4), "limit_usd": self.limit_usd},
            )
        raise QuotaExhaustedError(
            f"daily LLM budget of ${self.limit_usd:.2f} spent (${self.spent:.2f}); "
            f"{provider}:{model} not called"
        )

    def add(self, cost_usd: float | None) -> None:
        if not cost_usd:
            return
        self.spent += cost_usd
        if self.enabled and not self._warned and self.spent >= self.limit_usd * _WARN_RATIO:
            self._warned = True
            logger.warning(
                "Daily LLM budget at %.0f%%",
                100 * self.spent / self.limit_usd,
                extra={"spent_usd": round(self.spent, 4), "limit_usd": self.limit_usd},
            )

    async def _roll_day(self) -> None:
        today = self._today()
        if today == self._day:
            return
        self._day, self._warned, self._refused = today, False, False
        self.spent = 0.0
        if self._load is not None:
            start = datetime.combine(today, time.min, tzinfo=MARKET_TZ)
            try:
                self.spent = await self._load(start)
            except Exception as exc:
                logger.warning("Could not read today's LLM spend", extra={"error": str(exc)})
