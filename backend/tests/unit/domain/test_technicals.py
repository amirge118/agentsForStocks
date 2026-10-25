import numpy as np
import pandas as pd
import pytest

from app.domain import indicators
from app.domain.technicals import (
    analyze_price_history,
    mean_reversion_signal,
    momentum_signal,
    stat_arb_signal,
    trend_signal,
    volatility_signal,
)
from tests.unit.domain.conftest import make_ohlcv


@pytest.mark.unit
def test_uptrend_is_bullish(uptrend: pd.DataFrame) -> None:
    snapshot = analyze_price_history(uptrend)
    assert snapshot is not None
    assert snapshot.strategies["trend"] > 0
    assert snapshot.strategies["momentum"] > 0
    assert snapshot.composite > 0
    assert 0 <= snapshot.confidence <= 95


@pytest.mark.unit
def test_downtrend_is_bearish(downtrend: pd.DataFrame) -> None:
    snapshot = analyze_price_history(downtrend)
    assert snapshot is not None
    assert snapshot.strategies["trend"] < 0
    assert snapshot.label == "bearish"


@pytest.mark.unit
def test_short_history_returns_none() -> None:
    assert analyze_price_history(make_ohlcv([100.0] * 10)) is None
    assert analyze_price_history(pd.DataFrame()) is None


@pytest.mark.unit
def test_strategies_stay_in_range(uptrend: pd.DataFrame) -> None:
    closes = uptrend["Close"]
    for value in (
        trend_signal(uptrend, closes),
        mean_reversion_signal(closes),
        momentum_signal(uptrend, closes),
        volatility_signal(closes),
        stat_arb_signal(closes),
    ):
        assert -1.0 <= value <= 1.0


@pytest.mark.unit
def test_short_series_guards() -> None:
    df = make_ohlcv(np.linspace(100, 110, 15))
    closes = df["Close"]
    assert trend_signal(df, closes) == 0.0
    assert mean_reversion_signal(closes) == 0.0
    assert stat_arb_signal(closes) == 0.0


@pytest.mark.unit
def test_volume_spike_amplifies_momentum(uptrend: pd.DataFrame) -> None:
    spiked = uptrend.copy()
    spiked.iloc[-1, spiked.columns.get_loc("Volume")] = 10_000_000
    base = momentum_signal(uptrend, uptrend["Close"])
    assert momentum_signal(spiked, spiked["Close"]) >= base


@pytest.mark.unit
@pytest.mark.parametrize(
    "daily_move,expected",
    # annualised vol ≈ daily_move × √252: 8%, 20%, 32%, 63%
    [(0.005, 0.3), (0.0125, 0.0), (0.02, -0.2), (0.04, -0.5)],
)
def test_volatility_regimes(daily_move: float, expected: float) -> None:
    moves = np.where(np.arange(60) % 2 == 0, daily_move, -daily_move)
    closes = pd.Series(100 * np.exp(np.cumsum(moves)))
    assert volatility_signal(closes) == expected


@pytest.mark.unit
def test_indicator_helpers(uptrend: pd.DataFrame) -> None:
    closes = uptrend["Close"]
    assert 0 <= indicators.rsi(closes) <= 100
    upper, middle, lower = indicators.bollinger_bands(closes)
    assert upper > middle > lower
    assert indicators.atr(uptrend) > 0
    macd_line, signal_line, hist = indicators.macd(closes)
    assert hist == pytest.approx(macd_line - signal_line)
    assert indicators.sma(closes, 5).iloc[-1] == pytest.approx(closes.tail(5).mean())
    assert indicators.price_returns(closes.head(3), 10) == 0.0
    assert indicators.historical_volatility(closes.head(5)) == 0.0
    assert indicators.hurst_exponent(pd.Series([1.0] * 50)) == 0.5
    assert indicators.weighted_signal([]) == 0.0
    assert indicators.weighted_signal([(1.0, 1.0), (-1.0, 3.0)]) == -0.5
