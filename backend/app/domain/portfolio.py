"""
The portfolio ledger. Every movement of cash or shares is one entry; holdings, cash, cost
basis and realised P/L are derived by replaying the entries, never stored, so they can't
disagree with them.

  DEPOSIT / WITHDRAW   cash in / out (`amount`)
  BUY / SELL           shares at a price, plus a fee; a sale books realised P/L
  DIVIDEND             cash from a holding (`amount`)
  TRANSFER_IN          shares that arrive at a cost per share, without cash
                       (the opening positions of a portfolio kept elsewhere before)

Average cost: a buy adds shares x price + fee to the cost basis; a sale removes the
average cost of the shares sold, and books proceeds - fee - that cost. USD only.

A replay refuses a ledger that ever sells more shares than held, or takes cash below 0:
the same check guards a new entry, an edit and a deletion (a later entry may depend on
the one removed). Within a day, cash and shares come in before they go out.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

Kind = Literal["DEPOSIT", "WITHDRAW", "BUY", "SELL", "DIVIDEND", "TRANSFER_IN"]
KINDS: tuple[Kind, ...] = ("DEPOSIT", "WITHDRAW", "BUY", "SELL", "DIVIDEND", "TRANSFER_IN")
WITH_SHARES: frozenset[Kind] = frozenset({"BUY", "SELL", "TRANSFER_IN"})
WITH_AMOUNT: frozenset[Kind] = frozenset({"DEPOSIT", "WITHDRAW", "DIVIDEND"})
WITH_SYMBOL: frozenset[Kind] = frozenset({"BUY", "SELL", "TRANSFER_IN", "DIVIDEND"})

# Same-day order: what comes in before what goes out
_DAY_ORDER: dict[Kind, int] = {
    "DEPOSIT": 0,
    "TRANSFER_IN": 1,
    "DIVIDEND": 2,
    "SELL": 3,
    "BUY": 4,
    "WITHDRAW": 5,
}
ZERO = Decimal(0)


class LedgerError(ValueError):
    """The ledger breaks a rule; the message says which entry and why, in plain words."""


@dataclass(frozen=True)
class Entry:
    trade_date: date
    kind: Kind
    symbol: str | None = None
    shares: Decimal | None = None
    price: Decimal | None = None
    fee: Decimal = ZERO
    amount: Decimal | None = None
    id: int | None = None  # None: not stored yet (sorted after stored entries of its day)


@dataclass
class Position:
    shares: Decimal = ZERO
    cost: Decimal = ZERO  # cost basis of the shares held, fees included
    realised: Decimal = ZERO  # P/L booked by sales of this symbol
    dividends: Decimal = ZERO

    @property
    def avg_cost(self) -> Decimal | None:
        return self.cost / self.shares if self.shares > 0 else None


@dataclass
class Ledger:
    cash: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    deposited: Decimal = ZERO  # deposits - withdrawals
    transferred_in: Decimal = ZERO  # cost of the shares that came in without cash
    fees: Decimal = ZERO

    @property
    def held(self) -> dict[str, Position]:
        """Positions with shares today (a symbol sold out keeps its realised P/L only)."""
        return {s: p for s, p in self.positions.items() if p.shares > 0}

    @property
    def realised(self) -> Decimal:
        return sum((p.realised for p in self.positions.values()), ZERO)

    @property
    def dividends(self) -> Decimal:
        return sum((p.dividends for p in self.positions.values()), ZERO)

    @property
    def cost_basis(self) -> Decimal:
        return sum((p.cost for p in self.held.values()), ZERO)


def validate(entry: Entry) -> None:
    """The entry's own fields, before any replay."""
    if entry.kind not in KINDS:
        raise LedgerError(f"unknown kind {entry.kind!r}")
    if (entry.symbol is not None) != (entry.kind in WITH_SYMBOL):
        raise LedgerError(
            f"a {entry.kind} {'needs' if entry.kind in WITH_SYMBOL else 'takes no'} symbol"
        )
    if entry.kind in WITH_SHARES:
        if entry.shares is None or entry.shares <= 0:
            raise LedgerError(f"a {entry.kind} needs a number of shares above 0")
        if entry.price is None or entry.price <= 0:
            raise LedgerError(f"a {entry.kind} needs a price above 0")
        if entry.amount is not None:
            raise LedgerError(f"a {entry.kind} takes shares and a price, not an amount")
    else:
        if entry.amount is None or entry.amount <= 0:
            raise LedgerError(f"a {entry.kind} needs an amount above 0")
        if entry.shares is not None or entry.price is not None:
            raise LedgerError(f"a {entry.kind} takes an amount, not shares or a price")
    if entry.fee < 0:
        raise LedgerError("a fee can't be negative")
    if entry.fee > 0 and entry.kind not in ("BUY", "SELL"):
        raise LedgerError(f"a {entry.kind} has no fee")
    sold_for = (entry.shares or ZERO) * (entry.price or ZERO)
    if entry.kind == "SELL" and entry.fee > sold_for:
        raise LedgerError("a sale's fee can't be more than what the shares sold for")


def ordered(entries: Iterable[Entry]) -> list[Entry]:
    return sorted(
        entries,
        key=lambda e: (
            e.trade_date,
            _DAY_ORDER[e.kind],
            e.id is None,
            e.id or 0,
        ),
    )


def replay(entries: Iterable[Entry]) -> Ledger:
    """The ledger after every entry, in date order; LedgerError at the first broken rule."""
    ledger = Ledger()
    for entry in ordered(entries):
        validate(entry)
        _apply(ledger, entry)
    return ledger


def _apply(ledger: Ledger, e: Entry) -> None:
    when = e.trade_date.isoformat()
    if e.kind in WITH_AMOUNT:
        _apply_amount(ledger, e, e.amount or ZERO, when)
        return
    if e.symbol is None or e.shares is None or e.price is None:  # validate() rules this out
        raise LedgerError(f"a {e.kind} needs a symbol, shares and a price")
    position = ledger.positions.setdefault(e.symbol, Position())
    shares, price = e.shares, e.price
    if e.kind == "TRANSFER_IN":
        position.shares += shares
        position.cost += shares * price
        ledger.transferred_in += shares * price
    elif e.kind == "BUY":
        total = shares * price + e.fee
        _spend(ledger, total, f"buy {shares} {e.symbol} for {total} on {when}")
        position.shares += shares
        position.cost += total
        ledger.fees += e.fee
    else:  # SELL
        if shares > position.shares:
            raise LedgerError(
                f"can't sell {shares} {e.symbol} on {when}: only {position.shares} held then"
            )
        sold_cost = position.cost * shares / position.shares
        proceeds = shares * price - e.fee
        position.shares -= shares
        position.cost = ZERO if position.shares == 0 else position.cost - sold_cost
        position.realised += proceeds - sold_cost
        ledger.cash += proceeds
        ledger.fees += e.fee


def _apply_amount(ledger: Ledger, e: Entry, amount: Decimal, when: str) -> None:
    if e.kind == "DEPOSIT":
        ledger.cash += amount
        ledger.deposited += amount
    elif e.kind == "WITHDRAW":
        _spend(ledger, amount, f"withdraw {amount} on {when}")
        ledger.deposited -= amount
    else:  # DIVIDEND
        if e.symbol is None:  # validate() rules this out
            raise LedgerError("a DIVIDEND needs a symbol")
        ledger.cash += amount
        ledger.positions.setdefault(e.symbol, Position()).dividends += amount


def _spend(ledger: Ledger, amount: Decimal, what: str) -> None:
    if amount > ledger.cash:
        raise LedgerError(f"can't {what}: only {ledger.cash} cash then — record a deposit first")
    ledger.cash -= amount
