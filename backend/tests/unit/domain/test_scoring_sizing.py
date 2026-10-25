import numpy as np
import pandas as pd
import pytest

from app.domain.position_sizing import annualized_volatility, average_correlation, position_limit
from app.domain.scoring import to_action, weighted_score

WEIGHTS = {"valuation": 20, "moat": 15, "risk": 15, "growth": 10}


@pytest.mark.unit
def test_weighted_score_buy_with_missing_agents() -> None:
    results = {
        "valuation": {"signal": "bullish", "confidence": 100},
        "moat": {"signal": "bullish", "confidence": 80, "reasoning": "brand"},
    }
    score = weighted_score(results, WEIGHTS)
    assert score.score == pytest.approx(20 + 12)
    assert score.base_signal == "bullish"
    assert set(score.missing) == {"risk", "growth"}
    assert score.contributions[1].reasoning == "brand"
    assert score.base_confidence == 90.0


@pytest.mark.unit
def test_risk_override_caps_bullish_at_neutral() -> None:
    results = {
        "valuation": {"signal": "bullish", "confidence": 100},
        "moat": {"signal": "bullish", "confidence": 100},
        "risk": {"signal": "bearish", "confidence": 70},
    }
    score = weighted_score(results, WEIGHTS)
    assert score.risk_override_applied
    assert score.base_signal == "neutral"
    assert score.base_confidence <= 55


@pytest.mark.unit
def test_bearish_and_hold_paths() -> None:
    bearish = {name: {"signal": "bearish", "confidence": 100} for name in WEIGHTS}
    assert weighted_score(bearish, WEIGHTS).base_signal == "bearish"
    assert weighted_score({}, WEIGHTS).base_signal == "neutral"
    assert [to_action(s) for s in ("bullish", "bearish", "neutral")] == ["BUY", "SELL", "HOLD"]


def _prices(seed: int, sigma: float, n: int = 60) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        100 * np.cumprod(1 + rng.normal(0, sigma, n)), index=pd.bdate_range("2026-01-01", periods=n)
    )


@pytest.mark.unit
def test_position_limit_by_volatility_regime() -> None:
    calm = position_limit("A", _prices(1, 0.003), {}, portfolio_value=100_000)
    wild = position_limit("B", _prices(1, 0.05), {}, portfolio_value=100_000)
    assert calm.vol_regime == "low"
    assert wild.vol_regime == "very_high"
    assert calm.max_position_value > wild.max_position_value
    assert calm.adjusted_limit_pct <= 0.25


@pytest.mark.unit
def test_correlated_holdings_shrink_the_position() -> None:
    target = _prices(1, 0.01)
    alone = position_limit("A", target, {}, 100_000)
    crowded = position_limit("A", target, {"TWIN": target * 1.0}, 100_000)
    assert average_correlation(target, {"TWIN": target}) == pytest.approx(1.0)
    assert crowded.correlation_adj == 0.70
    assert crowded.adjusted_limit_pct < alone.adjusted_limit_pct
    assert average_correlation(target, {"SHORT": target.head(5)}) == 0.0
    assert annualized_volatility(target.head(3)) == 0.20
