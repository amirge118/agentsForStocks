"""
ProviderQuota — keeps one LLM provider inside its free-tier limits.

Free tiers fail with 429 long before they cost money, so each free provider gets
a client-side quota: requests and tokens per minute (sliding 60 s window) and per
day (reset at midnight in the provider's own time zone — Google resets at midnight
Pacific). Before a request the caller reserves its estimated tokens; acquire()
waits briefly for the window to free up, but when the wait would be long, the
daily budget is spent, or the provider just answered 429, it returns None at once,
so a FallbackChain moves on to the next provider instead of stalling the run.

The day's usage is seeded from the llm_calls ledger the first time it is needed,
so a worker restart (or a manual run in the API process) doesn't forget what the
scheduled run already used.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from app.core.clock import utcnow

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0
CHARS_PER_TOKEN = 4

# (provider, since) → (requests, tokens) already used since that instant
UsageLoader = Callable[[str, datetime], Awaitable[tuple[int, int]]]


@dataclass(frozen=True)
class QuotaLimits:
    rpm: int | None = None  # requests per minute
    tpm: int | None = None  # tokens (input + output) per minute
    rpd: int | None = None  # requests per day
    tpd: int | None = None  # tokens per day
    reset_tz: str = "UTC"  # the time zone whose midnight starts a new day


def estimate_tokens(system: str, prompt: str, max_tokens: int) -> int:
    """Worst-case size of a request: its text plus the whole output budget."""
    return (len(system) + len(prompt)) // CHARS_PER_TOKEN + max_tokens


class Reservation:
    """A slot taken by acquire(); settle() replaces the estimate with the real count."""

    def __init__(self, at: float, tokens: int) -> None:
        self.at = at
        self.tokens = tokens


class ProviderQuota:
    def __init__(
        self,
        name: str,
        limits: QuotaLimits,
        *,
        max_wait_seconds: float = 5.0,
        load_usage: UsageLoader | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = name
        self.limits = limits
        self._max_wait = max_wait_seconds
        self._load_usage = load_usage
        self._monotonic = monotonic
        self._now = now
        self._sleep = sleep
        self._tz = ZoneInfo(limits.reset_tz)
        self._lock = asyncio.Lock()
        self._window: deque[Reservation] = deque()
        self._cooldown_until = 0.0
        self._day: date | None = None
        self.day_requests = 0
        self.day_tokens = 0

    async def acquire(self, tokens: int) -> Reservation | None:
        """Reserve a request of ~`tokens`; None = skip this provider for now."""
        async with self._lock:
            await self._roll_day()
            if not self._fits_today(tokens):
                logger.info(
                    "LLM provider daily quota used up",
                    extra={
                        "provider": self.name,
                        "day_requests": self.day_requests,
                        "day_tokens": self.day_tokens,
                    },
                )
                return None
            while True:
                wait = self._wait_for(tokens)
                if wait is None or wait > self._max_wait:
                    logger.info(
                        "LLM provider rate limited, skipping",
                        extra={"provider": self.name, "wait_seconds": wait},
                    )
                    return None
                if wait <= 0:
                    break
                await self._sleep(wait)
            slot = Reservation(self._monotonic(), tokens)
            self._window.append(slot)
            self.day_requests += 1
            self.day_tokens += tokens
            return slot

    def settle(self, slot: Reservation, actual_tokens: int) -> None:
        """Count what the request really used (the reservation was a worst case)."""
        self.day_tokens = max(0, self.day_tokens + actual_tokens - slot.tokens)
        slot.tokens = actual_tokens

    def cool_down(self, seconds: float) -> None:
        """The provider answered 429: send nothing to it for `seconds`."""
        self._cooldown_until = max(self._cooldown_until, self._monotonic() + seconds)

    def _fits_today(self, tokens: int) -> bool:
        lim = self.limits
        if lim.rpd is not None and self.day_requests >= lim.rpd:
            return False
        return lim.tpd is None or self.day_tokens + tokens <= lim.tpd

    def _wait_for(self, tokens: int) -> float | None:
        """Seconds until a request of `tokens` fits the minute window (None = never)."""
        now = self._monotonic()
        while self._window and now - self._window[0].at >= _WINDOW_SECONDS:
            self._window.popleft()
        lim = self.limits
        if lim.tpm is not None and tokens > lim.tpm:
            return None
        waits = [self._cooldown_until - now]
        if lim.rpm is not None and len(self._window) >= lim.rpm:
            waits.append(self._window[len(self._window) - lim.rpm].at + _WINDOW_SECONDS - now)
        if lim.tpm is not None:
            excess = sum(s.tokens for s in self._window) + tokens - lim.tpm
            for slot in self._window:  # oldest first: wait until enough tokens age out
                if excess <= 0:
                    break
                excess -= slot.tokens
                waits.append(slot.at + _WINDOW_SECONDS - now)
        return max(waits)

    async def _roll_day(self) -> None:
        local = self._now().astimezone(self._tz)
        if local.date() == self._day:
            return
        self._day = local.date()
        self.day_requests = self.day_tokens = 0
        if self._load_usage is None:
            return
        start = datetime.combine(self._day, dtime.min, tzinfo=self._tz)
        try:
            self.day_requests, self.day_tokens = await self._load_usage(self.name, start)
        except Exception as exc:  # the ledger is a hint; never block calls on it
            logger.warning(
                "Could not load today's LLM usage", extra={"provider": self.name, "error": str(exc)}
            )
