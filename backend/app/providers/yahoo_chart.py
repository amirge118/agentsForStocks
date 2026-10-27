"""
Yahoo chart client — a backup for YFinanceClient's price data.

yfinance needs a session "crumb" from Yahoo, and Yahoo rate-limits handing one
out (HTTP 429) to busy addresses such as cloud hosts; without it quotes fail with
401 "Invalid Crumb". The public chart endpoint needs no crumb:

    https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=3mo&interval=1d

It gives daily OHLCV, split- and dividend-adjusted closes for a date range
(`adjclose`, what yfinance's auto_adjust returns) and the current quote (price,
previous close, 52-week range, name, currency) — not fundamentals (market cap,
P/E, margins). Requests go
through HttpClient (retry, rate limit, cache), and results are shaped like
yfinance's, so callers can't tell which source answered.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from app.core.symbols import validate_symbol
from app.providers.errors import ProviderError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo answers non-browser user agents with 429 more readily
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; agentsForStocks)"}
_OHLCV = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
# chart meta field → the yfinance Ticker.info field it stands in for
_QUOTE_FIELDS = {
    "regularMarketPrice": "regularMarketPrice",
    "chartPreviousClose": "previousClose",
    "currency": "currency",
    "longName": "longName",
    "shortName": "shortName",
    "fiftyTwoWeekHigh": "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow": "fiftyTwoWeekLow",
    "regularMarketVolume": "regularMarketVolume",
    "regularMarketDayHigh": "dayHigh",
    "regularMarketDayLow": "dayLow",
    "instrumentType": "quoteType",  # EQUITY, ETF, MUTUALFUND, ...
}
SOURCE = "yahoo_chart"


class YahooChartClient:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def get_history(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> pd.DataFrame:
        """OHLCV like yfinance's Ticker.history (empty when unavailable)."""
        result = await self._chart(symbol, period, interval)
        if result is None:
            return pd.DataFrame()
        return to_frame(result)

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """The quote fields of yfinance's Ticker.info that the chart carries ({} when none)."""
        result = await self._chart(symbol, "5d", "1d")
        return to_quote(result) if result is not None else {}

    async def get_adjusted_closes(self, symbol: str, start: date, end: date) -> pd.Series:
        """
        Split- and dividend-adjusted daily closes for the sessions in [start, end), like
        YFinanceClient.get_closes. Empty when Yahoo has none — and when the reply has no
        `adjclose`: an unadjusted close would score a dividend or a split as a loss.
        """
        result = await self._chart_query(
            symbol,
            {
                "period1": _epoch(start),
                "period2": _epoch(end),
                "interval": "1d",
                "includeAdjustedClose": "true",
            },
        )
        return to_adjusted_closes(result, start, end) if result is not None else _no_closes()

    async def _chart(self, symbol: str, period: str, interval: str) -> dict[str, Any] | None:
        return await self._chart_query(symbol, {"range": period, "interval": interval})

    async def _chart_query(self, symbol: str, params: dict[str, str]) -> dict[str, Any] | None:
        ticker = validate_symbol(symbol)
        try:
            data = await self._http.get_json(
                _CHART_URL.format(symbol=ticker), params=params, headers=_HEADERS
            )
        except ProviderError as exc:
            logger.warning("Yahoo chart unavailable", extra={"symbol": ticker, "error": str(exc)})
            return None
        results = ((data or {}).get("chart") or {}).get("result") or []
        return results[0] if results and isinstance(results[0], dict) else None


def to_frame(result: dict[str, Any]) -> pd.DataFrame:
    """chart.result[0] → DataFrame indexed by session time in the exchange's time zone."""
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    if not timestamps or not quote:
        return pd.DataFrame()
    tz = (result.get("meta") or {}).get("exchangeTimezoneName") or "UTC"
    index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(tz).normalize()
    frame = pd.DataFrame(
        {column: quote.get(key) or [None] * len(timestamps) for key, column in _OHLCV.items()},
        index=index,
    )
    # Yahoo leaves null rows for halted or not-yet-closed sessions
    return frame.dropna(subset=["Close"])


def to_adjusted_closes(result: dict[str, Any], start: date, end: date) -> pd.Series:
    """chart.result[0] → adjusted closes indexed by session date in [start, end)."""
    timestamps = result.get("timestamp") or []
    adjusted = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose")
    if not timestamps or not adjusted or len(adjusted) != len(timestamps):
        if timestamps:
            logger.warning(
                "Yahoo chart reply has no adjusted closes",
                extra={"symbol": (result.get("meta") or {}).get("symbol")},
            )
        return _no_closes()
    tz = (result.get("meta") or {}).get("exchangeTimezoneName") or "UTC"
    index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(tz).normalize()
    closes = pd.Series(adjusted, index=index, dtype=float, name="Close").dropna()
    days = closes.index.tz_localize(None)
    return closes[(days >= pd.Timestamp(start)) & (days < pd.Timestamp(end))]


def _epoch(day: date) -> str:
    return str(int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()))


def _no_closes() -> pd.Series:
    return pd.Series(dtype=float, name="Close")


def to_quote(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("meta") or {}
    quote = {info: meta[key] for key, info in _QUOTE_FIELDS.items() if meta.get(key) is not None}
    if "regularMarketPrice" in quote:
        quote["currentPrice"] = quote["regularMarketPrice"]
    return {**quote, "_source": SOURCE} if quote else {}
