"""
How the portfolio did over time: its value each session, the time-weighted return
against a benchmark, the week's change and its movers. Pure functions over the ledger
(app/domain/portfolio.py) and stored closes.

Value of a session = cash + shares held x that session's close. A symbol with no close
that day keeps its last one; before its first close, the price it came in at.

Money put in is not performance. A deposit or withdrawal, and shares transferred in
(valued at that session's close, not at their old cost), are flows: each session's
return is (value - flows) / previous value - 1, the flows taken as arriving at the close,
so new money neither earns nor dilutes that session. The first session (or the first
after everything was taken out) has no previous value: its return is value / flows - 1,
which counts the fees of that day's buys. Chaining the returns gives the time-weighted
return, which compares fairly with an index. Dividends and fees stay in the return.

The week runs from the last session before this week's Monday. A ledger that starts
inside the week starts from nothing: every flow since is money put in.
"""

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.portfolio import WITH_SHARES, ZERO, Entry, Ledger, apply, ordered

ONE = Decimal(1)
MOVERS = 3

Closes = Mapping[str, Mapping[date, Decimal]]


@dataclass(frozen=True)
class DayValue:
    day: date
    value: Decimal  # cash + holdings at the session's closes
    flow: Decimal  # money put in that session (taken out: negative)
    index: Decimal  # growth of 1 since the start, time-weighted
    benchmark: Decimal | None  # the benchmark's growth of 1 over the same sessions


@dataclass(frozen=True)
class Mover:
    symbol: str
    change: Decimal  # for the shares held now
    change_pct: Decimal


@dataclass(frozen=True)
class Performance:
    series: list[DayValue]
    week_start: date | None  # the session the week is measured from; None: the ledger is newer
    week_change: Decimal | None
    week_change_pct: Decimal | None
    gainers: list[Mover]
    losers: list[Mover]

    @property
    def total_return_pct(self) -> Decimal | None:
        return (self.series[-1].index - ONE) * 100 if self.series else None

    @property
    def benchmark_return_pct(self) -> Decimal | None:
        last = self.series[-1].benchmark if self.series else None
        return None if last is None else (last - ONE) * 100


EMPTY = Performance([], None, None, None, [], [])


class _Prices:
    """A symbol's price on a day: its close, else the last one before, else `fallback`."""

    def __init__(self, closes: Closes, fallback: Mapping[str, Decimal]) -> None:
        self._days = {s: sorted(c) for s, c in closes.items()}
        self._closes = closes
        self._fallback = fallback

    def on(self, symbol: str, day: date) -> Decimal | None:
        days = self._days.get(symbol, [])
        i = bisect_right(days, day)
        return self._closes[symbol][days[i - 1]] if i else self._fallback.get(symbol)


def week_start(sessions: Iterable[date], today: date) -> date | None:
    """The last session before this week's Monday."""
    monday = today - timedelta(days=today.weekday())
    return max((d for d in sessions if d < monday), default=None)


def performance(
    entries: Iterable[Entry], closes: Closes, sessions: Iterable[date], benchmark: str, today: date
) -> Performance:
    """
    `sessions`: the trading days to value (the benchmark's); those before the first entry
    are skipped. `closes` includes the benchmark's, and today's live prices if any.
    """
    entries = ordered(entries)
    if not entries:
        return EMPTY
    first = entries[0].trade_date
    days = sorted(d for d in set(sessions) if first <= d <= today)
    if not days:
        return EMPTY
    prices = _Prices(closes, _came_in_at(entries))
    series, ledger = _series(entries, prices, days)
    series = _with_benchmark(series, closes.get(benchmark, {}), first)

    start = week_start(sessions, today)
    base = next((v for v in series if v.day == start), None)
    last = series[-1]
    flows = sum((v.flow for v in series if base is None or v.day > base.day), ZERO)
    base_value, base_index = (base.value, base.index) if base else (ZERO, ONE)
    movers = _movers(ledger, prices, start, last.day)
    return Performance(
        series=series,
        week_start=base.day if base else None,
        week_change=last.value - base_value - flows,
        week_change_pct=(last.index / base_index - ONE) * 100,
        gainers=sorted((m for m in movers if m.change_pct > 0), key=lambda m: -m.change_pct)[
            :MOVERS
        ],
        losers=sorted((m for m in movers if m.change_pct < 0), key=lambda m: m.change_pct)[:MOVERS],
    )


def _came_in_at(entries: list[Entry]) -> dict[str, Decimal]:
    first: dict[str, Decimal] = {}
    for e in entries:
        if e.kind in WITH_SHARES and e.symbol and e.price:
            first.setdefault(e.symbol, e.price)
    return first


def _series(
    entries: list[Entry], prices: _Prices, days: list[date]
) -> tuple[list[DayValue], Ledger]:
    ledger = Ledger()
    i = 0
    series: list[DayValue] = []
    previous, index = ZERO, ONE
    for day in days:
        flow = ZERO
        while i < len(entries) and entries[i].trade_date <= day:
            apply(ledger, entries[i])
            flow += _flow(entries[i], prices, day)
            i += 1
        value = ledger.cash + sum(
            (p.shares * (prices.on(s, day) or ZERO) for s, p in ledger.held.items()), ZERO
        )
        if previous > 0:
            index *= (value - flow) / previous
        elif flow > 0:
            index *= value / flow
        series.append(DayValue(day, value, flow, index, None))
        previous = value
    return series, ledger


def _flow(entry: Entry, prices: _Prices, day: date) -> Decimal:
    if entry.kind == "DEPOSIT":
        return entry.amount or ZERO
    if entry.kind == "WITHDRAW":
        return -(entry.amount or ZERO)
    if entry.kind == "TRANSFER_IN" and entry.symbol and entry.shares:
        return entry.shares * (prices.on(entry.symbol, day) or entry.price or ZERO)
    return ZERO


def _with_benchmark(
    series: list[DayValue], closes: Mapping[date, Decimal], first: date
) -> list[DayValue]:
    """Growth of 1 from the benchmark's last close before the first entry (or its first)."""
    before = [d for d in closes if d < first]
    start_day = max(before) if before else min(closes, default=None)
    if start_day is None:
        return series
    bench = _Prices({"": closes}, {})
    start = closes[start_day]
    out = []
    for v in series:
        close = bench.on("", v.day)
        growth = None if close is None else close / start
        out.append(DayValue(v.day, v.value, v.flow, v.index, growth))
    return out


def _movers(ledger: Ledger, prices: _Prices, start: date | None, last: date) -> list[Mover]:
    """Each holding's move since the week began (with no close that far back: its entry price)."""
    movers = []
    for symbol, position in ledger.held.items():
        base = prices.on(symbol, start) if start else None
        base = base or prices.on(symbol, date.min)  # date.min: only the price it came in at
        now = prices.on(symbol, last)
        if base and now:
            movers.append(Mover(symbol, position.shares * (now - base), (now / base - ONE) * 100))
    return movers
