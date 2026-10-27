"""
Forward returns of a stored decision — pure functions, no I/O.

A decision dated D (the pipeline's market date) is scored as a position entered at
the first close *after* D and held `horizon` trading sessions of the stock. Not D's
own close: a manual run can happen intraday, before that close was known. The
benchmark is valued at its last close on or before the stock's entry and exit
sessions, so both returns span the same dates even when the calendars differ.

A window is scored only once it has fully traded; until then the outcome is
pending, never a partial return.

A call is right when the alpha points its way: bullish needs alpha > 0, bearish
alpha < 0, and neutral (HOLD) an alpha within a band that widens with the horizon.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import pandas as pd

# Trading sessions held: about one week, one month and one quarter
HORIZONS: tuple[int, ...] = (5, 20, 60)
# The horizon lessons and track records are judged on (about a month)
REVIEW_HORIZON = 20
# A HOLD is right when |alpha| stays within this over REVIEW_HORIZON sessions
HOLD_BAND = 0.02

OutcomeStatus = Literal["pending", "settled", "unavailable"]
Missing = Literal["stock", "benchmark"]


@dataclass(frozen=True)
class ForwardReturn:
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    raw_return: float
    benchmark_return: float

    @property
    def alpha(self) -> float:
        return self.raw_return - self.benchmark_return


@dataclass(frozen=True)
class Scored:
    """A forward return, or which series has not traded through the window yet."""

    outcome: ForwardReturn | None
    missing: Missing | None = None


def daily_closes(closes: pd.Series) -> pd.Series:
    """
    Closes keyed by the calendar day of their session, sorted, one per day.

    Yahoo stamps a daily bar at midnight in its exchange's time zone, so two series
    meet on their dates, not their instants. A missing or non-positive close is no
    price at all and is dropped.
    """
    closes = pd.to_numeric(closes, errors="coerce").dropna()
    closes = closes[closes > 0]
    index = pd.DatetimeIndex(closes.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    closes = closes.set_axis(index.normalize())
    return closes[~closes.index.duplicated(keep="last")].sort_index()


def window_end(decision_date: date, horizon: int) -> date:
    """
    The calendar day by which a `horizon`-session window has surely traded: about
    7 calendar days per 5 sessions, plus a week for holidays. Past it, a window that
    is still incomplete points at missing data, not at a window still running.
    """
    return decision_date + timedelta(days=round((horizon + 1) * 7 / 5) + 7)


def score(stock: pd.Series, benchmark: pd.Series, decision_date: date, horizon: int) -> Scored:
    """Forward return over `horizon` sessions after `decision_date`, against the benchmark."""
    if horizon < 1:
        raise ValueError(f"horizon must be at least one session, got {horizon}")
    closes = daily_closes(stock)
    after = closes[closes.index > pd.Timestamp(decision_date)]
    if len(after) <= horizon:
        return Scored(None, "stock")
    entry_at, exit_at = after.index[0], after.index[horizon]

    bench = daily_closes(benchmark)
    # It needs a close on or before entry, and must have traded through the exit
    if bench.empty or bench.index[0] > entry_at or bench.index[-1] < exit_at:
        return Scored(None, "benchmark")

    entry, exit_ = float(after.iloc[0]), float(after.iloc[horizon])
    bench_entry, bench_exit = float(bench.asof(entry_at)), float(bench.asof(exit_at))
    return Scored(
        ForwardReturn(
            entry_date=entry_at.date(),
            exit_date=exit_at.date(),
            entry_price=entry,
            exit_price=exit_,
            raw_return=(exit_ - entry) / entry,
            benchmark_return=(bench_exit - bench_entry) / bench_entry,
        )
    )


def hold_band(horizon: int) -> float:
    """The neutral band at `horizon` sessions: returns spread with the square root of time."""
    return HOLD_BAND * math.sqrt(horizon / REVIEW_HORIZON)


def is_hit(signal: str, alpha: float, horizon: int) -> bool:
    if signal == "bullish":
        return alpha > 0
    if signal == "bearish":
        return alpha < 0
    return abs(alpha) <= hold_band(horizon)


def captured_alpha(signal: str, alpha: float) -> float:
    """What following the call earned against the benchmark: long, short, or out (0)."""
    if signal == "bullish":
        return alpha
    if signal == "bearish":
        return -alpha
    return 0.0


@dataclass(frozen=True)
class SettledCall:
    """An agent's stored call on a symbol, with the settled outcome that followed it."""

    symbol: str
    decision_date: date
    exit_date: date
    horizon: int
    benchmark: str
    signal: str
    confidence: float
    reasoning: str
    raw_return: float
    alpha: float

    @property
    def hit(self) -> bool:
        return is_hit(self.signal, self.alpha, self.horizon)


@dataclass(frozen=True)
class Lesson:
    """What the outcome review concluded about one settled call."""

    symbol: str
    decision_date: date
    signal: str
    alpha: float
    text: str


@dataclass(frozen=True)
class TrackRecord:
    """Settled calls of one agent on one symbol, plus lessons, as of a date."""

    horizon: int
    benchmark: str
    calls: Sequence[SettledCall]
    lessons: Sequence[Lesson]

    @property
    def hits(self) -> int:
        return sum(1 for c in self.calls if c.hit)

    @property
    def mean_captured_alpha(self) -> float | None:
        if not self.calls:
            return None
        return sum(captured_alpha(c.signal, c.alpha) for c in self.calls) / len(self.calls)
