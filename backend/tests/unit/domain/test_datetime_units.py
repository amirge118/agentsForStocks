"""
The domain functions must not depend on the datetime resolution of their input.

pandas 3 infers it from the data: on pandas 3, yfinance 0.2.50 returns price history
indexed in seconds and earnings dates in microseconds, while the fakes in
tests/factories.py build nanosecond indexes. Each case here checks that
second / microsecond input gives exactly the nanosecond result.
"""

import pandas as pd
import pytest

from app.domain.earnings import next_earnings_date, post_earnings_reaction
from app.domain.market_scan import scan_metrics
from app.domain.position_sizing import annualized_volatility, average_correlation
from app.domain.technicals import analyze_price_history
from tests.factories import INFO, price_history

UNITS = ["us", "s"]


def _as_unit(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.as_unit(unit)
    return out


@pytest.mark.unit
@pytest.mark.parametrize("unit", UNITS)
def test_technicals_snapshot_ignores_index_resolution(unit: str) -> None:
    history = price_history()
    assert analyze_price_history(_as_unit(history, unit)) == analyze_price_history(history)


@pytest.mark.unit
@pytest.mark.parametrize("unit", UNITS)
def test_post_earnings_reaction_ignores_index_resolution(unit: str) -> None:
    history = price_history()
    surprises = [{"date": "2025-03-03"}, {"date": "2025-06-02"}, {"date": "2025-09-01"}]
    expected = post_earnings_reaction(surprises, history)
    assert expected.avg_1d_return_pct != 0.0  # the reports fall inside the history
    assert post_earnings_reaction(surprises, _as_unit(history, unit)) == expected


@pytest.mark.unit
@pytest.mark.parametrize("unit", UNITS)
def test_next_earnings_date_ignores_index_resolution(unit: str) -> None:
    dates = pd.DataFrame(
        {"EPS Estimate": [1.0, 1.0, 1.0]},
        index=pd.DatetimeIndex(
            ["2026-07-30 16:00", "2026-10-29 16:00", "2027-01-28 16:00"], tz="America/New_York"
        ),
    )
    now = pd.Timestamp("2026-10-26", tz="UTC")
    assert next_earnings_date(_as_unit(dates, unit), now) == next_earnings_date(dates, now)
    assert next_earnings_date(_as_unit(dates, unit), now) == "2026-10-29"


@pytest.mark.unit
@pytest.mark.parametrize("unit", UNITS)
def test_scan_metrics_ignore_index_resolution(unit: str) -> None:
    history = price_history()
    assert scan_metrics(INFO, _as_unit(history, unit)) == scan_metrics(INFO, history)


@pytest.mark.unit
@pytest.mark.parametrize("unit", UNITS)
def test_position_sizing_ignores_and_mixes_index_resolutions(unit: str) -> None:
    target = price_history(seed=3)["Close"]
    other = price_history(seed=7)["Close"]
    target_u = target.copy()
    target_u.index = target_u.index.as_unit(unit)

    assert annualized_volatility(target_u) == annualized_volatility(target)
    # One holding at another resolution than the target: the dates must still line up
    assert average_correlation(target_u, {"OTHER": other}) == pytest.approx(
        average_correlation(target, {"OTHER": other})
    )
