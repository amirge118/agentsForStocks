"""
yfinance client. yfinance is synchronous, so each call runs in a worker thread,
under the shared retry policy, rate limit ("yahoo" domain) and TTL cache.

Fields in Ticker.info can be None for valid tickers — always read them with .get().
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
import yfinance as yf
from opentelemetry import trace

from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.cache import TTLCache
from app.providers.errors import RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy, with_retry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

T = TypeVar("T")

_DOMAIN = "yahoo"


class YFinanceClient:
    def __init__(
        self,
        rate_limiter: RateLimiter,
        cache: TTLCache,
        retry_policy: RetryPolicy | None = None,
        ticker_factory: Callable[[str], Any] = yf.Ticker,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._retry = retry_policy or RetryPolicy()
        self._ticker = ticker_factory

    async def _call(self, key: tuple[Any, ...], fn: Callable[[], T]) -> T:
        log_ctx = {"domain": _DOMAIN, "path": f"{key[0]}/{key[1]}"}
        fetched = False

        async def _attempt() -> T:
            await self._rate_limiter.acquire(_DOMAIN)
            started = time.perf_counter()
            # yfinance does its own HTTP (not httpx), so it gets a span of its own
            with tracer.start_as_current_span(
                f"yfinance.{key[0]}", attributes={"symbol": str(key[1])}
            ):
                try:
                    value = await asyncio.to_thread(fn)
                except Exception as exc:
                    # yfinance surfaces network trouble as assorted exception types
                    raise RetryableError(f"yfinance {key[0]}: {exc}") from exc
            duration_ms = round((time.perf_counter() - started) * 1000)
            metrics.provider_duration.record(duration_ms, {"domain": _DOMAIN})
            logger.info("Provider request", extra={**log_ctx, "duration_ms": duration_ms})
            return value

        async def _load() -> T:
            nonlocal fetched
            fetched = True
            return await with_retry(_attempt, self._retry, label=f"yfinance.{key[0]}({key[1]})")

        value = await self._cache.get_or_load(("yfinance", *key), _load)
        metrics.provider_requests.add(
            1, {"domain": _DOMAIN, "outcome": "fetched" if fetched else "cache_hit"}
        )
        if not fetched:
            logger.debug("Provider cache hit", extra=log_ctx)
        return value

    async def get_info(self, symbol: str) -> dict:
        ticker = validate_symbol(symbol)
        return await self._call(("info", ticker), lambda: self._ticker(ticker).info or {})

    async def get_history(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> pd.DataFrame:
        """OHLCV history. Empty DataFrame when unavailable — callers must check .empty."""
        ticker = validate_symbol(symbol)

        def _fetch() -> pd.DataFrame:
            df = self._ticker(ticker).history(period=period, interval=interval)
            return df if df is not None else pd.DataFrame()

        return await self._call(("history", ticker, period, interval), _fetch)

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        ticker = validate_symbol(symbol)

        def _fetch() -> pd.DataFrame:
            df = self._ticker(ticker).earnings_dates
            return df if df is not None else pd.DataFrame()

        return await self._call(("earnings_dates", ticker), _fetch)

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        ticker = validate_symbol(symbol)

        def _fetch() -> list[dict]:
            df = self._ticker(ticker).get_insider_transactions()
            return df.to_dict("records") if df is not None and not df.empty else []

        return await self._call(("insider", ticker), _fetch)

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        ticker = validate_symbol(symbol)
        # yfinance 1.x asks Yahoo for `count` articles (default 10); slice in case it sends more
        return await self._call(
            ("news", ticker, count),
            lambda: (self._ticker(ticker).get_news(count=count) or [])[:count],
        )
