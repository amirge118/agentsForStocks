"""
Where the portfolio's money is, and what that exposes it to. Pure functions over a
valuation (app/domain/portfolio.py), what the agents stored, and daily closes.

  sectors   each sector's share of the whole portfolio (cash its own row), against an
            optional target: drift = share - target, in percentage points
  risk      the largest position, the cash share, the holdings' value-weighted beta (with
            how much of the holdings it covers: a missing beta is no evidence, not 0), and
            the pairs of holdings whose daily returns move together
  agents    the share of the portfolio under each of the agents' actions, and the
            holdings whose action changed since the agents' previous call

Only priced holdings count: a holding without a price has no value to weigh.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations
from statistics import StatisticsError, correlation

from app.domain.portfolio import ZERO, Valuation

CASH = "Cash"
FUND = "Fund"
UNKNOWN = "Not analysed yet"
TOGETHER = 0.8  # correlation of daily returns from which two holdings "move together"
MIN_RETURNS = 20  # fewer common daily returns than this: no reading
WINDOW = 60  # the most recent sessions read


@dataclass(frozen=True)
class SectorShare:
    sector: str
    value: Decimal
    weight: Decimal  # percent of the whole portfolio
    target: Decimal | None
    symbols: list[str]

    @property
    def drift(self) -> Decimal | None:
        return None if self.target is None else self.weight - self.target


@dataclass(frozen=True)
class Pair:
    first: str
    second: str
    correlation: float
    sessions: int  # the daily returns compared


@dataclass(frozen=True)
class Risk:
    largest: tuple[str, Decimal] | None  # symbol, weight
    cash_weight: Decimal | None
    beta: Decimal | None  # value-weighted, over the holdings with a beta
    beta_coverage: Decimal | None  # percent of the holdings' value that has a beta
    together: list[Pair]


@dataclass(frozen=True)
class Call:
    symbol: str
    action: str
    run_date: date
    previous: str | None  # the agents' call before this one; None: the first


@dataclass(frozen=True)
class ActionShare:
    action: str  # BUY / HOLD / SELL, or UNKNOWN
    value: Decimal
    weight: Decimal
    symbols: list[str]


def sectors(
    v: Valuation, sector_of: Mapping[str, str], targets: Mapping[str, Decimal]
) -> list[SectorShare]:
    """Largest first, cash last; a target for a sector not held shows at 0%."""
    groups: dict[str, list[tuple[str, Decimal]]] = {}
    for h in v.holdings:
        if h.value is not None:
            groups.setdefault(sector_of.get(h.symbol, UNKNOWN), []).append((h.symbol, h.value))
    for sector in targets:
        groups.setdefault(sector, [])
    rows = [
        _share(
            sector, sum((x for _, x in held), ZERO), v, targets.get(sector), [s for s, _ in held]
        )
        for sector, held in groups.items()
        if sector != CASH
    ]
    rows.sort(key=lambda r: (-r.value, r.sector))
    return [*rows, _share(CASH, v.cash, v, targets.get(CASH), [])]


def risk(
    v: Valuation,
    beta_of: Mapping[str, float | None],
    closes: Mapping[str, Mapping[date, Decimal]],
) -> Risk:
    priced = [h for h in v.holdings if h.value is not None and h.weight is not None]
    largest = max(priced, key=lambda h: h.value or ZERO, default=None)
    with_beta = [(h.value or ZERO, beta_of.get(h.symbol)) for h in priced]
    known = [(value, Decimal(str(b))) for value, b in with_beta if b is not None]
    known_value = sum((value for value, _ in known), ZERO)
    return Risk(
        largest=None if largest is None else (largest.symbol, largest.weight or ZERO),
        cash_weight=v.cash / v.total_value * 100 if v.total_value > 0 else None,
        beta=sum((value * b for value, b in known), ZERO) / known_value if known_value else None,
        beta_coverage=known_value / v.holdings_value * 100 if v.holdings_value > 0 else None,
        together=together([h.symbol for h in priced], closes),
    )


def together(symbols: list[str], closes: Mapping[str, Mapping[date, Decimal]]) -> list[Pair]:
    """Pairs whose daily returns over the last WINDOW sessions correlate at TOGETHER or more."""
    returns = {s: _returns(closes.get(s, {})) for s in symbols}
    pairs = []
    for a, b in combinations(sorted(symbols), 2):
        common = sorted(set(returns[a]) & set(returns[b]))[-WINDOW:]
        if len(common) < MIN_RETURNS:
            continue
        try:
            r = correlation([returns[a][d] for d in common], [returns[b][d] for d in common])
        except StatisticsError:  # a flat series: no reading
            continue
        if r >= TOGETHER:
            pairs.append(Pair(a, b, r, len(common)))
    return sorted(pairs, key=lambda p: -p.correlation)


def actions(v: Valuation, calls: Mapping[str, Call]) -> list[ActionShare]:
    """BUY, HOLD, SELL, then the holdings the agents haven't called; actions held only."""
    groups: dict[str, list[tuple[str, Decimal]]] = {}
    for h in v.holdings:
        if h.value is not None:
            call = calls.get(h.symbol)
            groups.setdefault(call.action if call else UNKNOWN, []).append((h.symbol, h.value))
    order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    return [
        ActionShare(
            action,
            value := sum((x for _, x in held), ZERO),
            value / v.total_value * 100 if v.total_value > 0 else ZERO,
            [s for s, _ in held],
        )
        for action, held in sorted(groups.items(), key=lambda kv: order.get(kv[0], 3))
    ]


def changed(calls: Mapping[str, Call]) -> list[Call]:
    return sorted(
        (c for c in calls.values() if c.previous is not None and c.previous != c.action),
        key=lambda c: c.symbol,
    )


def _share(
    sector: str, value: Decimal, v: Valuation, target: Decimal | None, symbols: list[str]
) -> SectorShare:
    weight = value / v.total_value * 100 if v.total_value > 0 else ZERO
    return SectorShare(sector, value, weight, target, sorted(symbols))


def _returns(closes: Mapping[date, Decimal]) -> dict[date, float]:
    days = sorted(closes)
    return {
        b: float(closes[b] / closes[a] - 1)
        for a, b in zip(days, days[1:], strict=False)
        if closes[a]
    }
