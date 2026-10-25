"""
In-memory TTL cache with in-flight de-duplication.

When several agents ask for the same data point at once (e.g. the FMP company
profile), only the first call reaches the API; the others await its result.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._values: dict[Hashable, tuple[float, Any]] = {}
        self._in_flight: dict[Hashable, asyncio.Future[Any]] = {}

    async def get_or_load(self, key: Hashable, loader: Callable[[], Awaitable[T]]) -> T:
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
            self._values[key] = (time.monotonic() + self._ttl, value)
            future.set_result(value)
            return value
        finally:
            del self._in_flight[key]

    def clear(self) -> None:
        self._values.clear()
