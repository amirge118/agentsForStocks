from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.providers.cache import TTLCache
from app.providers.http import HttpClient
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
async def make_http() -> AsyncIterator[Callable[[Handler], HttpClient]]:
    """Build HttpClients backed by an in-process MockTransport (no network)."""
    clients: list[HttpClient] = []

    def _make(handler: Handler) -> HttpClient:
        client = HttpClient(
            rate_limiter=RateLimiter({}, default_rps=1000),
            cache=TTLCache(ttl_seconds=60),
            retry_policy=RetryPolicy(max_attempts=3, timeout_seconds=1.0, base_backoff_seconds=0.0),
            transport=httpx.MockTransport(handler),
        )
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()
