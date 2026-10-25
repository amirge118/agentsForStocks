"""
Shared async HTTP client for JSON/text APIs (FMP, SEC EDGAR).

One httpx.AsyncClient (connection pooling) + per-domain rate limit + retry +
TTL cache. Provider clients build URLs; this class decides how they are fetched.
"""

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.providers.cache import TTLCache
from app.providers.errors import ProviderError, RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy, with_retry

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        rate_limiter: RateLimiter,
        cache: TTLCache,
        retry_policy: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._retry = retry_policy or RetryPolicy()
        self._client = httpx.AsyncClient(timeout=self._retry.timeout_seconds, transport=transport)

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        on_request: Callable[[], None] | None = None,
    ) -> Any:
        text = await self.get_text(url, params=params, headers=headers, on_request=on_request)
        return json.loads(text)

    async def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        on_request: Callable[[], None] | None = None,
    ) -> str:
        """
        Cached GET. on_request runs before every real network attempt (never on a
        cache hit) — providers use it to count calls against a quota.
        """
        key = (url, tuple(sorted((params or {}).items())))
        return await self._cache.get_or_load(
            key, lambda: self._fetch(url, params or {}, headers or {}, on_request)
        )

    async def _fetch(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        on_request: Callable[[], None] | None,
    ) -> str:
        domain = urlsplit(url).netloc

        async def _attempt() -> str:
            if on_request is not None:
                on_request()
            await self._rate_limiter.acquire(domain)
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise RetryableError(f"{type(exc).__name__} for {domain}") from exc
            if resp.status_code in _RETRYABLE_STATUS:
                raise RetryableError(f"HTTP {resp.status_code} from {domain}")
            if resp.status_code >= 400:
                # Client errors (bad key, unknown symbol) never succeed on retry
                raise ProviderError(f"HTTP {resp.status_code} from {domain}{urlsplit(url).path}")
            return resp.text

        return await with_retry(_attempt, self._retry, label=f"GET {domain}")

    async def aclose(self) -> None:
        await self._client.aclose()
