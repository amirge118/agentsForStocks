"""
Daily bars for the price chart: OHLCV plus SMA20 / SMA50 / RSI14 per bar.

Indicators are computed on the full fetched history and only then cut to the
displayed range, so the first visible bars already have their moving averages.
Undefined values (warm-up, flat prices) are None, never NaN, so they serialise as null.
"""

import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.domain.indicators import rsi_series, sma

PriceRange = Literal["1M", "3M", "6M", "1Y"]

# Displayed months, and the yfinance period to fetch so SMA50 is warm at the first bar
RANGES: dict[str, tuple[int, str]] = {
    "1M": (1, "6mo"),
    "3M": (3, "6mo"),
    "6M": (6, "1y"),
    "1Y": (12, "2y"),
}


@dataclass(frozen=True)
class PriceBar:
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    sma20: float | None
    sma50: float | None
    rsi14: float | None


def fetch_period(price_range: PriceRange) -> str:
    return RANGES[price_range][1]


def _num(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return None if math.isnan(number) else round(number, 4)


def price_bars(history: pd.DataFrame, price_range: PriceRange) -> list[PriceBar]:
    """Bars of the last `price_range` of `history` (yfinance daily OHLCV), oldest first."""
    if history is None or history.empty or "Close" not in history:
        return []
    df = history.dropna(subset=["Close"]).sort_index()
    if df.empty:
        return []
    closes = df["Close"].astype(float)
    indicators = pd.DataFrame(
        {"sma20": sma(closes, 20), "sma50": sma(closes, 50), "rsi14": rsi_series(closes, 14)},
        index=df.index,
    )
    months = RANGES[price_range][0]
    start = df.index[-1] - pd.DateOffset(months=months)
    visible = df.index > start
    bars = []
    for ts, row in df[visible].iterrows():
        ind = indicators.loc[ts]
        bars.append(
            PriceBar(
                date=pd.Timestamp(ts).date().isoformat(),
                open=_num(row.get("Open")),
                high=_num(row.get("High")),
                low=_num(row.get("Low")),
                close=round(float(row["Close"]), 4),
                volume=_num(row.get("Volume")),
                sma20=_num(ind["sma20"]),
                sma50=_num(ind["sma50"]),
                rsi14=_num(ind["rsi14"]),
            )
        )
    return bars
