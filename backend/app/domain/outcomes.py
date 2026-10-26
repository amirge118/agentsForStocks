"""
Forward returns of a stored decision — pure functions, no I/O.

A decision dated D (the pipeline's market date) is scored as a position entered at
the first close *after* D and held `horizon` trading sessions of the stock. Not D's
own close: a manual run can happen intraday, before that close was known. The
benchmark is valued at its last close on or before the stock's entry and exit
sessions, so both returns span the same dates even when the calendars differ.

A window is scored only once it has fully traded; until then the outcome is
pending, never a partial return.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import pandas as pd

# Trading sessions held: about one week, one month and one quarter
HORIZONS: tuple[int, ...] = (5, 20, 60)

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
