"""
Volatility-adjusted, correlation-aware position sizing (adapted from the
ai-hedge-fund risk manager). Not used by an agent yet — it is the building block
for the planned PortfolioHealthAgent / PortfolioManagerAgent.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

MAX_POSITION_PCT = 0.25

# (annualised vol upper bound, regime, max share of portfolio)
_VOL_REGIMES: tuple[tuple[float, str, float], ...] = (
    (0.15, "low", 0.25),
    (0.30, "medium", 0.20),
    (0.50, "high", 0.12),
)
_EXTREME_REGIME = ("very_high", 0.08)

# (min average |correlation| to holdings, size multiplier) — checked top-down
_CORRELATION_ADJUSTMENTS: tuple[tuple[float, float], ...] = (
    (0.80, 0.70),
    (0.60, 0.85),
    (0.40, 1.00),
    (0.20, 1.05),
    (0.00, 1.10),
)


@dataclass(frozen=True)
class PositionLimit:
    symbol: str
    volatility: float
    vol_regime: str
    base_limit_pct: float
    correlation_adj: float
    adjusted_limit_pct: float
    max_position_value: float


def annualized_volatility(prices: pd.Series, period: int = 20) -> float:
    """From daily log returns; assumes 20% when there are fewer than 5 prices."""
    if len(prices) < 5:
        return 0.20
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return float(log_ret.tail(period).std() * np.sqrt(252))


def average_correlation(target: pd.Series, holdings: dict[str, pd.Series]) -> float:
    """Mean absolute return correlation with each holding (≥ 10 shared days required)."""
    target_ret = np.log(target / target.shift(1)).dropna()
    corrs = []
    for prices in holdings.values():
        ret = np.log(prices / prices.shift(1)).dropna()
        common = target_ret.index.intersection(ret.index)
        if len(common) < 10:
            continue
        corr = float(target_ret[common].corr(ret[common]))
        if not np.isnan(corr):
            corrs.append(abs(corr))
    return float(np.mean(corrs)) if corrs else 0.0


def position_limit(
    symbol: str,
    prices: pd.Series,
    holdings: dict[str, pd.Series],
    portfolio_value: float,
) -> PositionLimit:
    vol = annualized_volatility(prices)
    regime, base_pct = _EXTREME_REGIME
    for upper, name, pct in _VOL_REGIMES:
        if vol < upper:
            regime, base_pct = name, pct
            break

    corr = average_correlation(prices, holdings)
    corr_adj = next(adj for threshold, adj in _CORRELATION_ADJUSTMENTS if corr >= threshold)
    adjusted = min(base_pct * corr_adj, MAX_POSITION_PCT)

    return PositionLimit(
        symbol=symbol,
        volatility=vol,
        vol_regime=regime,
        base_limit_pct=base_pct,
        correlation_adj=corr_adj,
        adjusted_limit_pct=adjusted,
        max_position_value=portfolio_value * adjusted,
    )
