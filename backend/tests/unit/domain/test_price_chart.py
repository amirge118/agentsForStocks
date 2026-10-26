import math

import numpy as np
import pandas as pd
import pytest

from app.domain.indicators import rsi, rsi_series
from app.domain.price_chart import RANGES, fetch_period, price_bars
from tests.factories import price_history


@pytest.mark.unit
def test_rsi_is_the_last_value_of_the_series() -> None:
    closes = price_history()["Close"]
    assert rsi(closes) == pytest.approx(float(rsi_series(closes).iloc[-1]))
    assert rsi_series(closes).dropna().between(0, 100).all()


@pytest.mark.unit
@pytest.mark.parametrize("price_range", list(RANGES))
def test_bars_cover_the_range_with_warm_indicators(price_range: str) -> None:
    history = price_history(days=520)
    bars = price_bars(history, price_range)  # type: ignore[arg-type]

    months = RANGES[price_range][0]
    assert 18 * months <= len(bars) <= 23 * months  # ~21 trading days a month
    assert bars[-1].date == history.index[-1].date().isoformat()
    assert [b.date for b in bars] == sorted(b.date for b in bars)
    # Indicators were computed before cutting, so even the first visible bar has them
    assert all(b.sma20 is not None and b.sma50 is not None and b.rsi14 is not None for b in bars)
    last = bars[-1]
    assert last.sma20 == pytest.approx(history["Close"].iloc[-20:].mean(), rel=1e-6)
    assert last.close == pytest.approx(history["Close"].iloc[-1], rel=1e-6)


@pytest.mark.unit
def test_short_history_has_null_warmup_and_never_nan() -> None:
    bars = price_bars(price_history(days=30), "1Y")
    assert len(bars) == 30
    assert bars[0].sma20 is None and bars[0].sma50 is None
    assert bars[-1].sma20 is not None and bars[-1].sma50 is None
    for bar in bars:
        for value in (bar.open, bar.sma20, bar.sma50, bar.rsi14, bar.volume):
            assert value is None or not math.isnan(value)


@pytest.mark.unit
def test_missing_closes_and_empty_input() -> None:
    history = price_history(days=60)
    history.iloc[10, history.columns.get_loc("Close")] = np.nan
    assert len(price_bars(history, "1Y")) == 59
    assert price_bars(pd.DataFrame(), "1M") == []
    assert price_bars(pd.DataFrame({"Open": [1.0]}), "1M") == []


@pytest.mark.unit
@pytest.mark.parametrize("unit", ["us", "s"])
def test_bars_ignore_index_resolution(unit: str) -> None:
    history = price_history()
    other = history.copy()
    other.index = other.index.as_unit(unit)
    assert price_bars(other, "3M") == price_bars(history, "3M")


@pytest.mark.unit
def test_fetch_period_leaves_room_for_sma50() -> None:
    assert fetch_period("1M") == "6mo"
    assert fetch_period("1Y") == "2y"
