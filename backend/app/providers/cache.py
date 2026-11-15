"""
In-memory TTL cache with in-flight de-duplication.

When several agents ask for the same data point at once (e.g. the FMP company
profile), only the first call reaches the API; the others await its result.

A value lives `ttl_seconds` unless the caller asks for its own TTL (a live quote
lives a minute, a company's statements hours). The cache holds at most
`max_entries`: a write that would go past it first drops the expired entries, then
the ones that expire soonest — so a process that runs for weeks doesn't keep growing.
This is the one interface the providers use; a shared cache (e.g. Redis, once there
are several API processes) can replace it without touching them.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_MAX_ENTRIES = 5000


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._values: dict[Hashable, tuple[float, Any]] = {}
        self._in_flight: dict[Hashable, asyncio.Future[Any]] = {}

    async def get_or_load(
        self,
        key: Hashable,
        loader: Callable[[], Awaitable[T]],
        ttl: float | None = None,
    ) -> T:
        cached = self._values.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

        pending = self._in_flight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            value = await loader()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved so an unawaited failure doesn't log noise
            raise
        else:
            self._store(key, value, self._ttl if ttl is None else ttl)
            future.set_result(value)
            return value
        finally:
            del self._in_flight[key]

    def __len__(self) -> int:
        return len(self._values)

    def clear(self) -> None:
        self._values.clear()

    def _store(self, key: Hashable, value: Any, ttl: float) -> None:
        now = time.monotonic()
        if key not in self._values and len(self._values) >= self._max:
            for stale in [k for k, (expires, _) in self._values.items() if expires <= now]:
                del self._values[stale]
            while len(self._values) >= self._max:
                del self._values[min(self._values, key=lambda k: self._values[k][0])]
        self._values[key] = (now + ttl, value)
