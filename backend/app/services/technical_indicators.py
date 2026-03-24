"""
Technical indicators — pure functions that operate on pandas Series/DataFrames.
Adapted from virattt/ai-hedge-fund technicals agent.

All functions accept a pd.Series of closing prices (or OHLCV DataFrame where noted)
and return a float or pd.Series. No side effects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Trend indicators
# ---------------------------------------------------------------------------

def ema(prices: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return prices.ewm(span=period, adjust=False).mean()


def sma(prices: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return prices.rolling(window=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> float:
    """
    Average Directional Index — measures trend strength (0-100).
    df must have columns: High, Low, Close.
    Returns latest ADX value. >25 = trending, <20 = ranging.
    """
    high, low, close = df["High"], df["Low"], df["Close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # Zero out where the other DM is larger
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    atr_s = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
    adx_series = dx.ewm(span=period, adjust=False).mean()
    return float(adx_series.iloc[-1])


# ---------------------------------------------------------------------------
# Momentum indicators
# ---------------------------------------------------------------------------

def rsi(prices: pd.Series, period: int = 14) -> float:
    """
    Relative Strength Index (0-100).
    >70 = overbought, <30 = oversold.
    """
    delta = prices.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    return float(rsi_series.iloc[-1])


def macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float]:
    """
    MACD line, signal line, histogram.
    Returns (macd_value, signal_value, histogram).
    """
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


def price_returns(prices: pd.Series, periods: int) -> float:
    """Percentage return over N periods."""
    if len(prices) <= periods:
        return 0.0
    return float((prices.iloc[-1] / prices.iloc[-periods - 1]) - 1)


# ---------------------------------------------------------------------------
# Volatility indicators
# ---------------------------------------------------------------------------

def bollinger_bands(
    prices: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float]:
    """
    Bollinger Bands: (upper, middle, lower).
    Interpretation: price near upper = overbought, near lower = oversold.
    """
    middle = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return float(upper.iloc[-1]), float(middle.iloc[-1]), float(lower.iloc[-1])


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Average True Range — volatility measure.
    df must have columns: High, Low, Close.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


def historical_volatility(prices: pd.Series, period: int = 20) -> float:
    """Annualized historical volatility from log returns."""
    log_returns = np.log(prices / prices.shift(1)).dropna()
    if len(log_returns) < period:
        return 0.0
    return float(log_returns.tail(period).std() * np.sqrt(252))


def z_score(prices: pd.Series, period: int = 20) -> float:
    """How many standard deviations price is from its rolling mean."""
    rolling_mean = prices.rolling(window=period).mean()
    rolling_std = prices.rolling(window=period).std()
    z = (prices - rolling_mean) / rolling_std
    return float(z.iloc[-1])


# ---------------------------------------------------------------------------
# Statistical indicators
# ---------------------------------------------------------------------------

def hurst_exponent(prices: pd.Series, max_lag: int = 20) -> float:
    """
    Hurst Exponent — measures mean reversion vs trend persistence.
    H < 0.5: mean-reverting
    H = 0.5: random walk
    H > 0.5: trending
    """
    lags = range(2, min(max_lag, len(prices) // 2))
    tau = []
    for lag in lags:
        pp = np.array(prices)
        tau.append(np.std(pp[lag:] - pp[:-lag]))

    if len(tau) < 2 or any(t == 0 for t in tau):
        return 0.5  # assume random walk on insufficient data

    reg = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(reg[0])


# ---------------------------------------------------------------------------
# Composite signal helpers
# ---------------------------------------------------------------------------

def normalize_signal(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """Clamp a signal value to [-1, 1] range."""
    return max(min_val, min(max_val, value))


def weighted_signal(signals: list[tuple[float, float]]) -> float:
    """
    Compute weighted average signal.
    signals: list of (signal_value, weight) tuples.
    signal_value should be in [-1, 1] where -1=bearish, +1=bullish.
    """
    total_weight = sum(w for _, w in signals)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in signals) / total_weight


def signal_to_label(value: float, bullish_threshold: float = 0.2, bearish_threshold: float = -0.2) -> str:
    """Convert a -1 to +1 signal value to bullish/bearish/neutral label."""
    if value >= bullish_threshold:
        return "bullish"
    if value <= bearish_threshold:
        return "bearish"
    return "neutral"
