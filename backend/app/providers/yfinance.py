"""
yfinance client. yfinance is synchronous, so each call runs in a worker thread,
under the shared retry policy, rate limit ("yahoo" domain) and TTL cache.

Fields in Ticker.info can be None for valid tickers — always read them with .get().

When yfinance can't get prices (Yahoo refuses its session "crumb", common on
cloud hosts), the optional YahooChartClient fallback fills in the price history
and the quote fields of `info` from Yahoo's public chart endpoint.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, TypeVar

import pandas as pd
import yfinance as yf
from opentelemetry import trace

from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.cache import TTLCache
from app.providers.errors import ProviderError, RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy, with_retry
from app.providers.yahoo_chart import YahooChartClient

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
        fallback: YahooChartClient | None = None,
        fundamentals: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        self._fallback = fallback
        self._fundamentals = fundamentals
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

    async def _optional(self, key: tuple[Any, ...], fn: Callable[[], T], empty: T) -> T:
        """
        Data with no chart fallback (earnings dates, insider trades, news): when yfinance
        can't get it, return `empty` so the agent runs on with a data gap
        instead of failing outright.
        """
        try:
            return await self._call(key, fn)
        except ProviderError as exc:
            if self._fallback is None:
                raise
            logger.warning(
                "yfinance data unavailable",
                extra={"call": key[0], "symbol": key[1], "error": str(exc)},
            )
            return empty

    async def get_info(self, symbol: str) -> dict:
        """
        Ticker.info. When Yahoo only half answers, the gaps are filled — yfinance's
        own values always win: with no price, the chart fallback adds the quote;
        with no market cap (a quote-only answer), `fundamentals` (FMP) adds the
        financial fields under the same names.
        """
        ticker = validate_symbol(symbol)
        try:
            info = await self._call(("info", ticker), lambda: self._ticker(ticker).info or {})
        except ProviderError:
            if self._fallback is None and self._fundamentals is None:
                raise
            info = {}
        own = {k: v for k, v in info.items() if v is not None}
        quote: dict = {}
        if self._fallback is not None and not _has_price(own):
            quote = await self._fallback.get_quote(ticker)
            if quote:
                _note_fallback("info", ticker)
        extra: dict = {}
        if self._fundamentals is not None and own.get("marketCap") is None:
            try:
                extra = await self._fundamentals(ticker)
            except ProviderError as exc:  # incl. the FMP daily budget
                logger.warning(
                    "Fundamentals fallback unavailable", extra={"symbol": ticker, "error": str(exc)}
                )
            if extra:
                _note_fallback("fundamentals", ticker)
        return {**extra, **quote, **own}

    async def get_history(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> pd.DataFrame:
        """OHLCV history. Empty DataFrame when unavailable — callers must check .empty."""
        ticker = validate_symbol(symbol)

        def _fetch() -> pd.DataFrame:
            df = self._ticker(ticker).history(period=period, interval=interval)
            return df if df is not None else pd.DataFrame()

        try:
            df = await self._call(("history", ticker, period, interval), _fetch)
        except ProviderError:
            if self._fallback is None:
                raise
            df = pd.DataFrame()
        if not df.empty or self._fallback is None:
            return df
        fallback = await self._fallback.get_history(ticker, period=period, interval=interval)
        if not fallback.empty:
            _note_fallback("history", ticker)
        return fallback

    async def get_closes(self, symbol: str, start: date, end: date) -> pd.Series:
        """
        Split- and dividend-adjusted daily closes for the sessions in [start, end) —
        `end` is exclusive, as in yfinance. Empty Series when Yahoo has none.
        """
        ticker = validate_symbol(symbol)

        def _fetch() -> pd.Series:
            df = self._ticker(ticker).history(
                start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=True
            )
            if df is None or df.empty or "Close" not in df:
                return pd.Series(dtype=float)
            return df["Close"]

        return await self._call(("closes", ticker, start.isoformat(), end.isoformat()), _fetch)

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        ticker = validate_symbol(symbol)

        def _fetch() -> pd.DataFrame:
            df = self._ticker(ticker).earnings_dates
            return df if df is not None else pd.DataFrame()

        return await self._optional(("earnings_dates", ticker), _fetch, pd.DataFrame())

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        ticker = validate_symbol(symbol)

        def _fetch() -> list[dict]:
            df = self._ticker(ticker).get_insider_transactions()
            return df.to_dict("records") if df is not None and not df.empty else []

        return await self._optional(("insider", ticker), _fetch, [])

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        ticker = validate_symbol(symbol)
        # yfinance 1.x asks Yahoo for `count` articles (default 10); slice in case it sends more
        return await self._optional(
            ("news", ticker, count),
            lambda: (self._ticker(ticker).get_news(count=count) or [])[:count],
            [],
        )


def _has_price(info: dict) -> bool:
    return any(info.get(k) is not None for k in ("regularMarketPrice", "currentPrice"))


def _note_fallback(call: str, ticker: str) -> None:
    logger.info(
        "yfinance had no data, used the Yahoo chart", extra={"call": call, "symbol": ticker}
    )
    metrics.provider_requests.add(1, {"domain": _DOMAIN, "outcome": "fallback"})
