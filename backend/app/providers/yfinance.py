"""
yfinance client. yfinance is synchronous, so each call runs in a worker thread,
under the shared retry policy, rate limit ("yahoo" domain) and TTL cache.

Fields in Ticker.info can be None for valid tickers — always read them with .get().
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
import yfinance as yf

from app.core.symbols import validate_symbol
from app.providers.cache import TTLCache
from app.providers.errors import RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy, with_retry

logger = logging.getLogger(__name__)

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
        async def _attempt() -> T:
            await self._rate_limiter.acquire(_DOMAIN)
            try:
                return await asyncio.to_thread(fn)
            except Exception as exc:
                # yfinance surfaces network trouble as assorted exception types
                raise RetryableError(f"yfinance {key[0]}: {exc}") from exc

        async def _load() -> T:
            return await with_retry(_attempt, self._retry, label=f"yfinance.{key[0]}({key[1]})")

        return await self._cache.get_or_load(("yfinance", *key), _load)

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
        # yfinance 0.2.x get_news() takes no count argument — slice instead
        return await self._call(
            ("news", ticker, count), lambda: (self._ticker(ticker).get_news() or [])[:count]
        )
