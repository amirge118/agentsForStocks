"""
yfinance wrapper — all stock data fetching goes through here.
Wraps every call with with_retry() for rate limiting and timeout protection.
Never call yfinance directly from agent or service code.
"""
import logging
import re

import pandas as pd
import yfinance as yf

from app.services.external_api_base import with_retry

logger = logging.getLogger(__name__)

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.]{1,10}$")


def validate_symbol(symbol: str) -> str:
    """
    Sanitize and validate a stock ticker symbol.
    Raises ValueError for invalid input — call at API boundary, not inside agents.
    """
    clean = re.sub(r"[^A-Z0-9.]", "", symbol.upper())[:10]
    if not _SYMBOL_PATTERN.match(clean):
        raise ValueError(f"Invalid symbol: {symbol!r}")
    return clean


async def get_info(symbol: str) -> dict:
    """
    Fetch the full info dict for a symbol.
    Always use .get() on the result — fields can be None for valid tickers.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> dict:
        info = yf.Ticker(validated).info
        if not info or info.get("regularMarketPrice") is None and info.get("trailingPE") is None:
            logger.warning("yfinance returned empty info for %s", validated)
        return info or {}

    return await with_retry(_fetch, label=f"yfinance.info({validated})")


async def get_history(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch OHLCV history. period examples: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y.
    Returns empty DataFrame on failure (callers must check .empty).
    """
    validated = validate_symbol(symbol)

    def _fetch() -> pd.DataFrame:
        return yf.Ticker(validated).history(period=period, interval=interval)

    df: pd.DataFrame = await with_retry(
        _fetch, label=f"yfinance.history({validated}, {period})"
    )
    return df if not df.empty else pd.DataFrame()


async def get_earnings_dates(symbol: str) -> pd.DataFrame:
    """
    Fetch upcoming and recent earnings dates with EPS estimates.
    Returns empty DataFrame if unavailable (common for small-caps and ETFs).
    """
    validated = validate_symbol(symbol)

    def _fetch() -> pd.DataFrame:
        df = yf.Ticker(validated).earnings_dates
        return df if df is not None else pd.DataFrame()

    return await with_retry(_fetch, label=f"yfinance.earnings_dates({validated})")


async def get_options_chain(symbol: str, expiry: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch options chain (calls, puts) for a given expiry date (YYYY-MM-DD).
    If expiry is None, uses the nearest available expiry.
    Returns (calls_df, puts_df) — both empty DataFrames on failure.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> tuple[pd.DataFrame, pd.DataFrame]:
        ticker = yf.Ticker(validated)
        target_expiry = expiry or ticker.options[0]
        chain = ticker.option_chain(target_expiry)
        return chain.calls, chain.puts

    return await with_retry(_fetch, label=f"yfinance.options({validated})")
