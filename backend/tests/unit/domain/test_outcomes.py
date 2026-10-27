from datetime import date, timedelta

import pandas as pd
import pytest

from app.domain.outcomes import (
    SettledCall,
    TrackRecord,
    TrackStats,
    agent_tracks,
    captured_alpha,
    confidence_bucket,
    daily_closes,
    hold_band,
    is_hit,
    score,
    window_end,
)


def closes(start: str, values: list[float], tz: str | None = "America/New_York") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values), tz=tz))


# Mon 2026-10-05 … : decision on Mon, entry Tue
STOCK = closes("2026-10-05", [100, 101, 102, 103, 104, 105, 106, 107])
BENCH = closes("2026-10-05", [50, 50, 50.5, 50.5, 51, 51, 51.5, 51.5])


@pytest.mark.unit
def test_entry_is_first_close_after_the_decision_day() -> None:
    scored = score(STOCK, BENCH, date(2026, 10, 5), horizon=5)
    o = scored.outcome
    assert o is not None and scored.missing is None
    assert (o.entry_date, o.exit_date) == (date(2026, 10, 6), date(2026, 10, 13))
    assert (o.entry_price, o.exit_price) == (101, 106)
    assert o.raw_return == pytest.approx(5 / 101)
    assert o.benchmark_return == pytest.approx(1.5 / 50)
    assert o.alpha == pytest.approx(5 / 101 - 1.5 / 50)


@pytest.mark.unit
def test_partial_window_is_pending_not_a_partial_return() -> None:
    # 7 sessions after the decision: a 7-session window needs an 8th
    assert score(STOCK, BENCH, date(2026, 10, 5), horizon=7).missing == "stock"
    assert score(STOCK, BENCH, date(2026, 10, 5), horizon=6).outcome is not None


@pytest.mark.unit
def test_weekend_decision_enters_on_monday() -> None:
    o = score(STOCK, BENCH, date(2026, 10, 10), horizon=2).outcome  # a Saturday
    assert o is not None and o.entry_date == date(2026, 10, 12)


@pytest.mark.unit
def test_benchmark_must_cover_entry_and_exit() -> None:
    short = BENCH.iloc[:5]  # stops before the exit
    assert score(STOCK, short, date(2026, 10, 5), horizon=5).missing == "benchmark"
    late = BENCH.iloc[3:]  # starts after the entry
    assert score(STOCK, late, date(2026, 10, 5), horizon=2).missing == "benchmark"
    assert score(STOCK, pd.Series(dtype=float), date(2026, 10, 5), 1).missing == "benchmark"


@pytest.mark.unit
def test_benchmark_holiday_uses_its_last_close() -> None:
    # Benchmark has no bar on the stock's exit day: valued at the close before it
    bench = BENCH.drop(BENCH.index[6])
    o = score(STOCK, bench, date(2026, 10, 5), horizon=5).outcome  # exit 2026-10-13
    assert o is not None and o.benchmark_return == pytest.approx((51 - 50) / 50)


@pytest.mark.unit
def test_calendars_meet_on_dates_not_instants() -> None:
    # A UTC-stamped series and a New York one: same sessions, different instants
    stock = closes("2026-10-05", [10, 11, 12, 13], tz="UTC")
    o = score(stock, BENCH, date(2026, 10, 5), horizon=2).outcome
    assert o is not None and o.benchmark_return == pytest.approx(0.5 / 50)


@pytest.mark.unit
def test_missing_and_bad_closes_are_dropped() -> None:
    raw = closes("2026-10-05", [100, float("nan"), 0, -1, 104])
    clean = daily_closes(raw)
    assert list(clean) == [100, 104]
    assert clean.index.tz is None
    assert daily_closes(pd.Series(dtype=float)).empty


@pytest.mark.unit
def test_duplicate_days_keep_the_last_bar() -> None:
    index = pd.DatetimeIndex(["2026-10-06 00:00", "2026-10-05 00:00", "2026-10-06 16:00"])
    clean = daily_closes(pd.Series([1.0, 2.0, 3.0], index=index))
    assert list(clean) == [2.0, 3.0]


@pytest.mark.unit
def test_window_end_leaves_room_for_weekends_and_holidays() -> None:
    assert window_end(date(2026, 10, 5), 5) == date(2026, 10, 5) + timedelta(days=15)
    assert window_end(date(2026, 10, 5), 20) > date(2026, 11, 2)  # 20 sessions ≈ 4 weeks


@pytest.mark.unit
def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError):
        score(STOCK, BENCH, date(2026, 10, 5), horizon=0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("signal", "alpha", "horizon", "hit"),
    [
        ("bullish", 0.01, 20, True),
        ("bullish", -0.01, 20, False),
        ("bearish", -0.01, 20, True),
        ("bearish", 0.0, 20, False),
        ("neutral", 0.019, 20, True),
        ("neutral", -0.021, 20, False),
        ("neutral", 0.03, 60, True),  # the band widens with the horizon (±3.5% at 60)
        ("neutral", 0.015, 5, False),  # and narrows below it (±1% at 5)
    ],
)
def test_hit_rules(signal: str, alpha: float, horizon: int, hit: bool) -> None:
    assert is_hit(signal, alpha, horizon) is hit


@pytest.mark.unit
def test_hold_band_scales_with_the_square_root_of_time() -> None:
    assert hold_band(20) == pytest.approx(0.02)
    assert hold_band(80) == pytest.approx(0.04)


@pytest.mark.unit
def test_track_record_counts_hits_and_captured_alpha() -> None:
    def call(signal: str, alpha: float) -> SettledCall:
        return SettledCall(
            "AAPL", date(2026, 9, 1), date(2026, 9, 30), 20, "SPY", signal, 60.0, "", 0.0, alpha
        )

    track = TrackRecord(
        20, "SPY", (call("bullish", 0.04), call("bearish", 0.02), call("neutral", 0.01)), ()
    )
    assert track.hits == 2
    # long +4%, short against +2% = -2%, out = 0  → mean +0.67%
    assert track.mean_captured_alpha == pytest.approx(0.02 / 3)
    assert TrackRecord(20, "SPY", (), ()).mean_captured_alpha is None
    assert captured_alpha("bearish", -0.03) == pytest.approx(0.03)


@pytest.mark.unit
def test_confidence_buckets_cover_0_to_100() -> None:
    assert [confidence_bucket(c) for c in (0, 39.9, 40, 79.9, 80, 100)] == [
        "0-40",
        "0-40",
        "40-60",
        "60-80",
        "80-100",
        "80-100",
    ]


@pytest.mark.unit
def test_agent_tracks_group_by_signal_and_confidence() -> None:
    def call(signal: str, alpha: float, confidence: float) -> SettledCall:
        return SettledCall(
            "AAPL",
            date(2026, 9, 1),
            date(2026, 9, 30),
            20,
            "SPY",
            signal,
            confidence,
            "",
            0.0,
            alpha,
        )

    tracks = agent_tracks(
        [
            ("moat", call("bullish", 0.03, 85)),
            ("recommendation", call("bullish", 0.02, 70)),
            ("recommendation", call("bearish", 0.01, 70)),
            ("recommendation", call("neutral", 0.005, 30)),
        ]
    )
    assert [t.agent for t in tracks] == ["recommendation", "moat"]  # recommendation first
    rec = tracks[0]
    assert (rec.overall.calls, rec.overall.hits) == (3, 2)
    assert rec.overall.hit_rate == pytest.approx(2 / 3)
    assert list(rec.by_signal) == ["bullish", "neutral", "bearish"]
    assert rec.by_signal["bearish"].hits == 0
    assert {k: v.calls for k, v in rec.by_confidence.items()} == {"0-40": 1, "60-80": 2}
    assert TrackStats(0, 0, None).hit_rate is None
