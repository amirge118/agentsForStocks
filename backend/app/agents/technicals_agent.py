"""
TechnicalsAgent — 5-strategy weighted technical analysis.
Adapted from virattt/ai-hedge-fund technicals.py.

Strategies (weights):
  1. Trend Following    (25%) — EMA 8/21/55 + ADX
  2. Mean Reversion     (20%) — Bollinger Bands + RSI + Z-score
  3. Momentum           (25%) — Multi-timeframe returns + volume
  4. Volatility         (15%) — Historical vol regime + ATR
  5. Statistical Arb    (15%) — Hurst Exponent + skewness/kurtosis

Final signal = weighted average of 5 strategies, mapped to bullish/bearish/neutral.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import llm_service
from app.services import yfinance_service as yf_svc
from app.services.technical_indicators import (
    adx, atr, bollinger_bands, ema, historical_volatility,
    hurst_exponent, price_returns, rsi, signal_to_label,
    weighted_signal, z_score,
)

logger = logging.getLogger(__name__)

_STRATEGY_WEIGHTS = [
    ("trend",       0.25),
    ("mean_rev",    0.20),
    ("momentum",    0.25),
    ("volatility",  0.15),
    ("stat_arb",    0.15),
]

_SYSTEM_PROMPT = """\
You are a quantitative technical analyst. You receive strategy signals (-1 to +1 scale)
and their weighted combination. Produce a final investment signal.
Return JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100), reasoning (string, max 200 chars).
"""


class TechnicalsAgent(AgentBase):
    agent_type = "technicals"

    async def fetch_data(self, symbol: str) -> dict:
        history = await yf_svc.get_history(symbol, period="1y", interval="1d")
        return {"symbol": symbol, "history": history}

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        df: pd.DataFrame = data["history"]

        if df.empty or len(df) < 30:
            return _insufficient_data(symbol, self.agent_type)

        closes = df["Close"]
        strategies = {
            "trend":      _trend_signal(df, closes),
            "mean_rev":   _mean_reversion_signal(closes),
            "momentum":   _momentum_signal(df, closes),
            "volatility": _volatility_signal(df, closes),
            "stat_arb":   _stat_arb_signal(closes),
        }

        composite = weighted_signal([(strategies[k], w) for k, w in _STRATEGY_WEIGHTS])
        label = signal_to_label(composite)
        confidence = min(abs(composite) * 100.0, 95.0)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        strat_lines = "\n".join(
            f"  {k} (weight={w:.0%}): {strategies[k]:+.3f}" for k, w in _STRATEGY_WEIGHTS
        )
        user_prompt = f"""
Symbol: {symbol}
Strategy signals (-1=bearish, +1=bullish):
{strat_lines}
Composite weighted signal: {composite:+.3f} → {label}
Prior knowledge base context: {context_str}

Produce the final signal JSON.
"""
        result = await llm_service.call_claude(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AnalystSignal,
        )

        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "strategies": strategies,
            "composite": composite,
            "summary": f"Technicals: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }


# ---------------------------------------------------------------------------
# Strategy signal functions — each returns float in [-1, +1]
# ---------------------------------------------------------------------------

def _trend_signal(df: pd.DataFrame, closes: pd.Series) -> float:
    """EMA crossover + ADX trend strength."""
    if len(closes) < 55:
        return 0.0

    e8 = float(ema(closes, 8).iloc[-1])
    e21 = float(ema(closes, 21).iloc[-1])
    e55 = float(ema(closes, 55).iloc[-1])
    price = float(closes.iloc[-1])

    # Count how many EMAs the price is above
    above = sum([price > e8, price > e21, price > e55])
    ema_signal = (above / 3) * 2 - 1  # maps 0→-1, 1.5→0, 3→+1

    adx_val = adx(df) if len(df) >= 14 else 20.0
    adx_multiplier = min(adx_val / 25.0, 1.5)  # scale: ADX=25 → 1.0x, ADX=50 → 2.0x (capped)

    return np.clip(ema_signal * adx_multiplier, -1.0, 1.0)


def _mean_reversion_signal(closes: pd.Series) -> float:
    """Bollinger Bands + RSI + Z-score."""
    if len(closes) < 20:
        return 0.0

    price = float(closes.iloc[-1])
    upper, middle, lower = bollinger_bands(closes)
    bb_range = upper - lower

    # BB position: -1 (at lower) to +1 (at upper), inverted for mean reversion
    bb_pos = (price - middle) / (bb_range / 2) if bb_range > 0 else 0.0
    bb_signal = -bb_pos  # mean reversion: above band → bearish, below → bullish

    rsi_val = rsi(closes)
    # RSI: >70 overbought (-1), <30 oversold (+1)
    if rsi_val > 70:
        rsi_signal = -1.0
    elif rsi_val < 30:
        rsi_signal = 1.0
    else:
        rsi_signal = -(rsi_val - 50) / 50.0

    z = z_score(closes)
    z_signal = np.clip(-z / 2.0, -1.0, 1.0)  # z>2 → bearish, z<-2 → bullish

    return float(np.clip((bb_signal + rsi_signal + z_signal) / 3, -1.0, 1.0))


def _momentum_signal(df: pd.DataFrame, closes: pd.Series) -> float:
    """Multi-timeframe returns with volume confirmation."""
    r1m = price_returns(closes, 21)
    r3m = price_returns(closes, 63) if len(closes) > 63 else 0.0
    r6m = price_returns(closes, 126) if len(closes) > 126 else 0.0

    # Weight: 1m=40%, 3m=35%, 6m=25%
    mom = r1m * 0.40 + r3m * 0.35 + r6m * 0.25
    mom_signal = np.clip(mom * 5, -1.0, 1.0)  # scale: 20% move → ±1.0

    # Volume confirmation
    vol_signal = 0.0
    if "Volume" in df.columns and len(df) >= 20:
        avg_vol = float(df["Volume"].tail(20).mean())
        latest_vol = float(df["Volume"].iloc[-1])
        if avg_vol > 0:
            vol_ratio = latest_vol / avg_vol
            # High volume amplifies momentum direction
            if vol_ratio > 1.5:
                vol_signal = np.sign(mom_signal) * 0.2

    return float(np.clip(mom_signal + vol_signal, -1.0, 1.0))


def _volatility_signal(df: pd.DataFrame, closes: pd.Series) -> float:
    """
    Volatility regime — low vol = slight bullish, high vol = slight bearish.
    Not a strong directional signal; more of a risk modifier.
    """
    vol = historical_volatility(closes)
    if vol < 0.15:
        return 0.3   # low vol → slight bullish bias
    if vol < 0.25:
        return 0.0   # normal
    if vol < 0.40:
        return -0.2  # elevated vol → mild bearish
    return -0.5       # high vol → bearish (uncertainty premium)


def _stat_arb_signal(closes: pd.Series) -> float:
    """
    Hurst Exponent + skewness/kurtosis.
    Hurst < 0.5: mean-reverting → use with mean reversion
    Hurst > 0.5: trending → use with trend following
    """
    if len(closes) < 20:
        return 0.0

    h = hurst_exponent(closes)
    log_ret = np.log(closes / closes.shift(1)).dropna().tail(20)

    skew = float(log_ret.skew())
    kurt = float(log_ret.kurt())

    # Positive skew + low kurtosis in trending regime → bullish
    # Negative skew + high kurtosis → bearish (fat left tail)
    skew_signal = np.clip(skew / 2.0, -0.5, 0.5)
    kurt_penalty = np.clip(-kurt / 10.0, -0.3, 0.0)

    hurst_modifier = (h - 0.5) * 2  # trending (h>0.5) amplifies, mean-rev (h<0.5) dampens

    return float(np.clip((skew_signal + kurt_penalty) * (1 + hurst_modifier), -1.0, 1.0))


def _insufficient_data(symbol: str, agent_type: str) -> dict:
    return {
        "signal": "neutral",
        "confidence": 0.0,
        "reasoning": "Insufficient price history for technical analysis.",
        "strategies": {},
        "composite": 0.0,
        "summary": f"Technicals: neutral (0%) — insufficient data",
        "agent_type": agent_type,
        "symbol": symbol,
    }
