"""
Risk service — volatility-adjusted position sizing and correlation adjustments.
Adapted from virattt/ai-hedge-fund risk_manager agent.

Not an agent — called by signal_aggregator to add risk context to signals.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PositionLimit:
    """Position sizing result for one symbol."""
    def __init__(
        self,
        symbol: str,
        volatility: float,
        vol_regime: str,
        base_limit_pct: float,
        correlation_adj: float,
        adjusted_limit_pct: float,
        max_position_value: float,
    ) -> None:
        self.symbol = symbol
        self.volatility = volatility          # annualized historical vol
        self.vol_regime = vol_regime          # "low" | "medium" | "high" | "very_high"
        self.base_limit_pct = base_limit_pct  # % of portfolio before correlation adj
        self.correlation_adj = correlation_adj
        self.adjusted_limit_pct = adjusted_limit_pct
        self.max_position_value = max_position_value


# Volatility regime thresholds (annualized)
_VOL_REGIMES = [
    (0.15, "low",       0.25),   # vol < 15%  → 25% max allocation
    (0.30, "medium",    0.20),   # vol < 30%  → 20%
    (0.50, "high",      0.12),   # vol < 50%  → 12%
    (1.00, "very_high", 0.08),   # vol >= 50% → 8%
]

# Correlation adjustments
_CORR_ADJUSTMENTS = [
    (0.80, 0.70),   # very high correlation → reduce by 30%
    (0.60, 0.85),   # high correlation       → reduce by 15%
    (0.40, 1.00),   # moderate               → no adjustment
    (0.20, 1.05),   # low                    → slight increase
    (0.00, 1.10),   # very low               → small increase
]


def calculate_position_limit(
    symbol: str,
    prices: pd.Series,
    portfolio_prices: dict[str, pd.Series],
    portfolio_value: float,
) -> PositionLimit:
    """
    Calculate volatility-adjusted, correlation-aware position limit.

    Args:
        symbol: Ticker being sized
        prices: Close price Series for the symbol
        portfolio_prices: Dict of {ticker: close_prices} for existing holdings
        portfolio_value: Total portfolio value in USD
    """
    vol = _annualized_volatility(prices)

    # Volatility regime → base limit
    base_pct = 0.08  # fallback for extreme volatility
    vol_regime = "very_high"
    for threshold, regime, limit_pct in _VOL_REGIMES:
        if vol < threshold:
            base_pct = limit_pct
            vol_regime = regime
            break

    # Correlation adjustment
    corr = _average_correlation(prices, portfolio_prices)
    corr_adj = 1.0
    for threshold, adjustment in _CORR_ADJUSTMENTS:
        if corr >= threshold:
            corr_adj = adjustment
            break

    adjusted_pct = min(base_pct * corr_adj, 0.25)  # hard cap at 25%
    max_value = portfolio_value * adjusted_pct

    return PositionLimit(
        symbol=symbol,
        volatility=vol,
        vol_regime=vol_regime,
        base_limit_pct=base_pct,
        correlation_adj=corr_adj,
        adjusted_limit_pct=adjusted_pct,
        max_position_value=max_value,
    )


def _annualized_volatility(prices: pd.Series, period: int = 20) -> float:
    """Annualized volatility from daily log returns."""
    if len(prices) < 5:
        return 0.20  # default 20% when insufficient data
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return float(log_ret.tail(period).std() * np.sqrt(252))


def _average_correlation(
    target_prices: pd.Series,
    portfolio_prices: dict[str, pd.Series],
) -> float:
    """Average correlation of target to existing portfolio holdings."""
    if not portfolio_prices:
        return 0.0

    corrs = []
    target_ret = np.log(target_prices / target_prices.shift(1)).dropna()

    for ticker, prices in portfolio_prices.items():
        port_ret = np.log(prices / prices.shift(1)).dropna()
        # Align on common dates
        common = target_ret.index.intersection(port_ret.index)
        if len(common) < 10:
            continue
        corr = float(target_ret[common].corr(port_ret[common]))
        if not np.isnan(corr):
            corrs.append(abs(corr))

    return float(np.mean(corrs)) if corrs else 0.0
