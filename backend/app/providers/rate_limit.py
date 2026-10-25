"""Per-domain rate limiting — spaces out requests so each domain sees at most N calls/second."""

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """
    Minimum-interval limiter keyed by domain. Concurrent callers for the same
    domain queue up; different domains never block each other.
    """

    def __init__(self, requests_per_second: dict[str, float], default_rps: float = 5.0) -> None:
        self._intervals = {d: 1.0 / rps for d, rps in requests_per_second.items()}
        self._default_interval = 1.0 / default_rps
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._next_slot: dict[str, float] = defaultdict(float)

    async def acquire(self, domain: str) -> None:
        interval = self._intervals.get(domain, self._default_interval)
        async with self._locks[domain]:
            now = time.monotonic()
            wait = self._next_slot[domain] - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_slot[domain] = max(now, self._next_slot[domain]) + interval
