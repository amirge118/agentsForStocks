"""
Yahoo chart client — a backup for YFinanceClient's price data.

yfinance needs a session "crumb" from Yahoo, and Yahoo rate-limits handing one
out (HTTP 429) to busy addresses such as cloud hosts; without it quotes fail with
401 "Invalid Crumb". The public chart endpoint needs no crumb:

    https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=3mo&interval=1d

It gives daily OHLCV and the current quote (price, previous close, 52-week range,
name, currency) — not fundamentals (market cap, P/E, margins). Requests go
through HttpClient (retry, rate limit, cache), and results are shaped like
yfinance's, so callers can't tell which source answered.
"""

import logging
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

    async def _chart(self, symbol: str, period: str, interval: str) -> dict[str, Any] | None:
        ticker = validate_symbol(symbol)
        try:
            data = await self._http.get_json(
                _CHART_URL.format(symbol=ticker),
                params={"range": period, "interval": interval},
                headers=_HEADERS,
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


def to_quote(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("meta") or {}
    quote = {info: meta[key] for key, info in _QUOTE_FIELDS.items() if meta.get(key) is not None}
    if "regularMarketPrice" in quote:
        quote["currentPrice"] = quote["regularMarketPrice"]
    return {**quote, "_source": SOURCE} if quote else {}
