"""
Five-strategy technical analysis (adapted from virattt/ai-hedge-fund technicals.py).

Strategies (weights): trend 25%, mean reversion 20%, momentum 25%,
volatility 15%, statistical arbitrage 15%. Each returns a value in [-1, +1].
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.domain.indicators import (
    adx,
    bollinger_bands,
    ema,
    historical_volatility,
    hurst_exponent,
    price_returns,
    rsi,
    weighted_signal,
    z_score,
)
from app.domain.signals import SignalLabel, clamp, label_from_score

STRATEGY_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("trend", 0.25),
    ("mean_rev", 0.20),
    ("momentum", 0.25),
    ("volatility", 0.15),
    ("stat_arb", 0.15),
)
MIN_HISTORY_DAYS = 30


@dataclass(frozen=True)
class TechnicalSnapshot:
    strategies: dict[str, float]
    composite: float
    label: SignalLabel
    confidence: float


def analyze_price_history(df: pd.DataFrame) -> TechnicalSnapshot | None:
    """Composite technical signal from daily OHLCV, or None with < 30 days of history."""
    if df.empty or len(df) < MIN_HISTORY_DAYS:
        return None
    closes = df["Close"]
    strategies = {
        "trend": trend_signal(df, closes),
        "mean_rev": mean_reversion_signal(closes),
        "momentum": momentum_signal(df, closes),
        "volatility": volatility_signal(closes),
        "stat_arb": stat_arb_signal(closes),
    }
    composite = weighted_signal([(strategies[name], w) for name, w in STRATEGY_WEIGHTS])
    return TechnicalSnapshot(
        strategies=strategies,
        composite=composite,
        label=label_from_score(composite),
        confidence=min(abs(composite) * 100.0, 95.0),
    )


def trend_signal(df: pd.DataFrame, closes: pd.Series) -> float:
    """Price position vs EMA 8/21/55, scaled by ADX trend strength."""
    if len(closes) < 55:
        return 0.0
    price = float(closes.iloc[-1])
    above = sum(price > float(ema(closes, span).iloc[-1]) for span in (8, 21, 55))
    ema_signal = (above / 3) * 2 - 1  # 0 above → -1, all 3 above → +1
    adx_multiplier = min(adx(df) / 25.0, 1.5)  # ADX 25 → 1.0x, capped at 1.5x
    return clamp(ema_signal * adx_multiplier, -1.0, 1.0)


def mean_reversion_signal(closes: pd.Series) -> float:
    """Bollinger position + RSI + z-score, inverted: stretched up → bearish."""
    if len(closes) < 20:
        return 0.0
    price = float(closes.iloc[-1])
    upper, middle, lower = bollinger_bands(closes)
    half_range = (upper - lower) / 2
    bb_signal = -(price - middle) / half_range if half_range > 0 else 0.0

    rsi_val = rsi(closes)
    if rsi_val > 70:
        rsi_signal = -1.0
    elif rsi_val < 30:
        rsi_signal = 1.0
    else:
        rsi_signal = -(rsi_val - 50) / 50.0

    z_signal = clamp(-z_score(closes) / 2.0, -1.0, 1.0)
    return clamp((bb_signal + rsi_signal + z_signal) / 3, -1.0, 1.0)


def momentum_signal(df: pd.DataFrame, closes: pd.Series) -> float:
    """1m/3m/6m returns (40/35/25%), amplified by a volume spike."""
    r1m = price_returns(closes, 21)
    r3m = price_returns(closes, 63)
    r6m = price_returns(closes, 126)
    mom_signal = clamp((r1m * 0.40 + r3m * 0.35 + r6m * 0.25) * 5, -1.0, 1.0)  # 20% → ±1

    vol_boost = 0.0
    if "Volume" in df.columns and len(df) >= 20:
        avg_vol = float(df["Volume"].tail(20).mean())
        if avg_vol > 0 and float(df["Volume"].iloc[-1]) / avg_vol > 1.5:
            vol_boost = float(np.sign(mom_signal)) * 0.2
    return clamp(mom_signal + vol_boost, -1.0, 1.0)


def volatility_signal(closes: pd.Series) -> float:
    """Volatility regime as a mild risk modifier: calm → slightly bullish."""
    vol = historical_volatility(closes)
    if vol < 0.15:
        return 0.3
    if vol < 0.25:
        return 0.0
    if vol < 0.40:
        return -0.2
    return -0.5


def stat_arb_signal(closes: pd.Series) -> float:
    """Return skew/kurtosis, amplified when the Hurst exponent says the series trends."""
    if len(closes) < 20:
        return 0.0
    log_ret = np.log(closes / closes.shift(1)).dropna().tail(20)
    skew_signal = clamp(float(log_ret.skew()) / 2.0, -0.5, 0.5)
    kurt_penalty = clamp(-float(log_ret.kurt()) / 10.0, -0.3, 0.0)
    hurst_modifier = (hurst_exponent(closes) - 0.5) * 2
    return clamp((skew_signal + kurt_penalty) * (1 + hurst_modifier), -1.0, 1.0)
