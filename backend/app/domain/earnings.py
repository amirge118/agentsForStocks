"""Earnings surprise history and post-earnings price reaction."""

from dataclasses import dataclass

import pandas as pd

from app.domain.stats import mean

QUARTERS_ANALYZED = 8


@dataclass(frozen=True)
class SurpriseStats:
    beats: int
    total: int
    beat_rate: float  # 0-1
    avg_surprise_pct: float


@dataclass(frozen=True)
class PriceReaction:
    avg_1d_return_pct: float
    avg_3d_return_pct: float


def surprise_pct(actual: float | None, estimated: float | None) -> float | None:
    if actual is None or estimated is None or estimated == 0:
        return None
    return (actual - estimated) / abs(estimated) * 100


def reported(surprises: list[dict]) -> list[dict]:
    """Quarters already reported — FMP lists the upcoming one first, with epsActual = None."""
    return [s for s in surprises if s.get("epsActual") is not None]


def surprise_stats(surprises: list[dict]) -> SurpriseStats:
    pcts: list[float] = []
    beats = 0
    for s in reported(surprises)[:QUARTERS_ANALYZED]:
        pct = surprise_pct(s.get("epsActual"), s.get("epsEstimated"))
        if pct is None:
            continue
        pcts.append(pct)
        beats += s["epsActual"] > s["epsEstimated"]
    total = len(pcts)
    return SurpriseStats(
        beats=beats,
        total=total,
        beat_rate=beats / total if total else 0.0,
        avg_surprise_pct=mean(pcts),
    )


def post_earnings_reaction(surprises: list[dict], history: pd.DataFrame) -> PriceReaction:
    """Average 1- and 3-trading-day returns from the first session on/after each report."""
    if history.empty or not surprises:
        return PriceReaction(0.0, 0.0)
    close = history["Close"].copy()
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)

    returns_1d: list[float] = []
    returns_3d: list[float] = []
    for s in surprises[:QUARTERS_ANALYZED]:
        try:
            report_day = pd.Timestamp(str(s.get("date"))[:10])
        except ValueError:
            continue
        after = close[close.index >= report_day]
        if len(after) < 4:
            continue
        p0, p1, p3 = float(after.iloc[0]), float(after.iloc[1]), float(after.iloc[3])
        if p0 > 0:
            returns_1d.append((p1 - p0) / p0 * 100)
            returns_3d.append((p3 - p0) / p0 * 100)
    return PriceReaction(mean(returns_1d), mean(returns_3d))


def next_earnings_date(earnings_dates: pd.DataFrame, now: pd.Timestamp | None = None) -> str:
    """ISO date of the next scheduled report, or 'Unknown'."""
    if earnings_dates is None or earnings_dates.empty:
        return "Unknown"
    current = now or pd.Timestamp.now(tz="UTC")
    try:
        future = earnings_dates[earnings_dates.index > current]
    except TypeError:  # tz-naive index
        future = earnings_dates[earnings_dates.index > current.tz_localize(None)]
    return str(future.index.min().date()) if not future.empty else "Unknown"
