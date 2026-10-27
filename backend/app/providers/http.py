"""
Shared async HTTP client for JSON/text APIs (FMP, SEC EDGAR).

One httpx.AsyncClient (connection pooling) + per-domain rate limit + retry +
TTL cache. Provider clients build URLs; this class decides how they are fetched.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.observability import metrics
from app.providers.cache import TTLCache
from app.providers.errors import ProviderError, RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RETRYABLE_STATUS, RetryPolicy, with_retry

logger = logging.getLogger(__name__)


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
        fetched = False

        async def _load() -> str:
            nonlocal fetched
            fetched = True
            return await self._fetch(url, params or {}, headers or {}, on_request)

        text = await self._cache.get_or_load(key, _load)
        parts = urlsplit(url)
        metrics.provider_requests.add(
            1, {"domain": parts.netloc, "outcome": "fetched" if fetched else "cache_hit"}
        )
        if not fetched:
            logger.debug("Provider cache hit", extra={"domain": parts.netloc, "path": parts.path})
        return text

    async def _fetch(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        on_request: Callable[[], None] | None,
    ) -> str:
        domain = urlsplit(url).netloc
        path = urlsplit(url).path  # never the query string: FMP sends its key there
        attempts = 0

        async def _attempt() -> str:
            nonlocal attempts
            attempts += 1
            if on_request is not None:
                on_request()
            await self._rate_limiter.acquire(domain)
            started = time.perf_counter()
            try:
                resp = await self._client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise RetryableError(f"{type(exc).__name__} for {domain}") from exc
            duration_ms = round((time.perf_counter() - started) * 1000)
            metrics.provider_duration.record(duration_ms, {"domain": domain})
            logger.info(
                "Provider request",
                extra={
                    "domain": domain,
                    "path": path,
                    "status": resp.status_code,
                    "duration_ms": duration_ms,
                    "attempt": attempts,
                },
            )
            if resp.status_code in RETRYABLE_STATUS:
                raise RetryableError(f"HTTP {resp.status_code} from {domain}")
            if resp.status_code >= 300:
                # Client errors (bad key, unknown symbol) never succeed on retry. Redirects
                # aren't followed — they would bypass the per-domain rate limit — and their
                # empty body must not be mistaken for content (it was, for SEC archive URLs)
                where = resp.headers.get("location", "")
                detail = f" → {where}" if 300 <= resp.status_code < 400 and where else ""
                raise ProviderError(
                    f"HTTP {resp.status_code} from {domain}{urlsplit(url).path}{detail}",
                    status=resp.status_code,
                )
            return resp.text

        return await with_retry(_attempt, self._retry, label=f"GET {domain}")

    async def aclose(self) -> None:
        await self._client.aclose()
