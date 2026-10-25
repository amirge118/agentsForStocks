"""
Time helpers — the single source of "today" for the whole backend.

Agent results are keyed by the US market date (America/New_York), not by the
server's local date. A run at 21:00 ET on a UTC server is still "today" for
the market, so every component must use market_today() instead of date.today().
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")


def utcnow() -> datetime:
    """Timezone-aware current UTC time (datetime.utcnow() is deprecated)."""
    return datetime.now(UTC)


def market_today(now: datetime | None = None) -> date:
    """Current date in the US market timezone."""
    current = now or utcnow()
    return current.astimezone(MARKET_TZ).date()
