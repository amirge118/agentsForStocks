from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.portfolio import Entry, LedgerError, replay, validate

DAY = date(2026, 11, 2)
NEXT = date(2026, 11, 3)
LATER = date(2026, 11, 4)


def deposit(amount: str, day: date = DAY) -> Entry:
    return Entry(day, "DEPOSIT", amount=D(amount))


def buy(symbol: str, shares: str, price: str, fee: str = "0", day: date = DAY) -> Entry:
    return Entry(day, "BUY", symbol, D(shares), D(price), D(fee))


def sell(symbol: str, shares: str, price: str, fee: str = "0", day: date = NEXT) -> Entry:
    return Entry(day, "SELL", symbol, D(shares), D(price), D(fee))


@pytest.mark.unit
def test_buying_spends_cash_and_builds_a_cost_basis_with_the_fee() -> None:
    ledger = replay([deposit("10000"), buy("MSFT", "10", "520", fee="1")])
    assert ledger.cash == D("4799")
    msft = ledger.held["MSFT"]
    assert (msft.shares, msft.cost, msft.avg_cost) == (D("10"), D("5201"), D("520.1"))
    assert ledger.cost_basis == D("5201") and ledger.fees == D("1")


@pytest.mark.unit
def test_a_partial_sale_books_pl_against_the_average_cost() -> None:
    ledger = replay(
        [
            deposit("12000"),
            buy("MSFT", "10", "500"),
            buy("MSFT", "10", "600", day=NEXT),  # average 550
            sell("MSFT", "4", "560", fee="2", day=LATER),
        ]
    )
    msft = ledger.held["MSFT"]
    assert msft.shares == D("16") and msft.avg_cost == D("550")
    assert msft.realised == D("4") * D("560") - D("2") - D("4") * D("550")  # +38
    assert ledger.cash == D("12000") - D("11000") + D("2238")  # = 3238


@pytest.mark.unit
def test_selling_out_keeps_the_realised_pl_but_not_the_position() -> None:
    ledger = replay([deposit("1000"), buy("EOSE", "100", "5"), sell("EOSE", "100", "3")])
    assert "EOSE" not in ledger.held
    assert ledger.realised == D("-200") and ledger.cost_basis == 0
    assert ledger.cash == D("800")


@pytest.mark.unit
def test_opening_positions_come_in_without_cash_at_their_cost() -> None:
    ledger = replay(
        [
            Entry(DAY, "TRANSFER_IN", "GOOG", D("20"), D("150")),
            deposit("500"),
            Entry(NEXT, "DIVIDEND", "GOOG", amount=D("4.2")),
            Entry(LATER, "WITHDRAW", amount=D("100")),
        ]
    )
    assert ledger.held["GOOG"].cost == D("3000") and ledger.transferred_in == D("3000")
    assert ledger.cash == D("404.2") and ledger.dividends == D("4.2")
    assert ledger.deposited == D("400")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([buy("MSFT", "1", "500")], "record a deposit first"),
        ([deposit("100"), buy("MSFT", "1", "100", fee="1")], "only 100 cash"),
        ([deposit("100"), Entry(DAY, "WITHDRAW", amount=D("101"))], "can't withdraw"),
        ([deposit("1000"), buy("MSFT", "1", "500"), sell("MSFT", "2", "500")], "only 1 held"),
        ([sell("MSFT", "1", "500")], "only 0 held"),
    ],
)
def test_a_ledger_that_spends_what_it_doesnt_have_is_refused(
    entries: list[Entry], message: str
) -> None:
    with pytest.raises(LedgerError, match=message):
        replay(entries)


@pytest.mark.unit
def test_within_a_day_money_comes_in_before_it_goes_out() -> None:
    # Recorded in the "wrong" order on the same day: the buy is stored first
    ledger = replay(
        [
            Entry(DAY, "BUY", "MSFT", D("1"), D("500"), id=1),
            Entry(DAY, "DEPOSIT", amount=D("500"), id=2),
        ]
    )
    assert ledger.cash == 0
    # On different days the order is the date's: a buy before its deposit is refused
    with pytest.raises(LedgerError):
        replay([buy("MSFT", "1", "500", day=DAY), deposit("500", day=NEXT)])


@pytest.mark.unit
def test_removing_an_entry_a_later_one_needs_is_refused() -> None:
    entries = [deposit("1000"), buy("MSFT", "2", "400", day=NEXT)]
    replay(entries)
    with pytest.raises(LedgerError, match="record a deposit first"):
        replay(entries[1:])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (Entry(DAY, "DEPOSIT", "MSFT", amount=D("1")), "takes no symbol"),
        (Entry(DAY, "BUY", shares=D("1"), price=D("1")), "needs symbol"),
        (Entry(DAY, "BUY", "MSFT", D("0"), D("1")), "shares above 0"),
        (Entry(DAY, "BUY", "MSFT", D("1"), None), "price above 0"),
        (Entry(DAY, "BUY", "MSFT", D("1"), D("1"), amount=D("1")), "not an amount"),
        (Entry(DAY, "DEPOSIT"), "amount above 0"),
        (Entry(DAY, "DEPOSIT", amount=D("1"), shares=D("1")), "not shares"),
        (Entry(DAY, "DEPOSIT", amount=D("1"), fee=D("1")), "has no fee"),
        (Entry(DAY, "BUY", "MSFT", D("1"), D("1"), D("-1")), "can't be negative"),
        (Entry(DAY, "SELL", "MSFT", D("1"), D("1"), D("2")), "more than what the shares sold"),
        (Entry(DAY, "SPLIT", "MSFT", D("1"), D("1")), "unknown kind"),  # type: ignore[arg-type]
    ],
)
def test_an_entry_with_the_wrong_fields_for_its_kind_is_refused(entry: Entry, message: str) -> None:
    with pytest.raises(LedgerError, match=message):
        validate(entry)


@pytest.mark.unit
def test_an_empty_ledger_is_all_zero() -> None:
    ledger = replay([])
    assert (ledger.cash, ledger.realised, ledger.cost_basis, ledger.held) == (0, 0, 0, {})


@pytest.mark.unit
def test_the_ledger_at_todays_prices() -> None:
    from app.domain.portfolio import Price, valuation

    ledger = replay(
        [
            deposit("10000"),
            buy("MSFT", "10", "500"),  # cost 5000
            buy("EOSE", "100", "5"),  # cost 500
            Entry(DAY, "TRANSFER_IN", "OLD", D("1"), D("10")),  # no price anywhere
        ]
    )
    prices = {
        "MSFT": Price(D("520"), D("510"), DAY),
        "EOSE": Price(D("4"), None, DAY, stale=True),
    }
    v = valuation(ledger, prices)
    assert v.cash == D("4500") and v.holdings_value == D("5600")
    assert v.total_value == D("10100") and v.unpriced == ["OLD"]
    assert [h.symbol for h in v.holdings] == ["MSFT", "EOSE", "OLD"]  # largest value first
    msft, eose, old = v.holdings
    assert (msft.value, msft.unrealised, msft.day_change) == (D("5200"), D("200"), D("100"))
    assert msft.weight == D("5200") / D("10100") * 100
    assert eose.unrealised == D("-100") and eose.day_change is None and eose.price.stale
    assert (old.value, old.unrealised, old.weight) == (None, None, None)  # not valued at 0
    assert v.unrealised == D("100") and v.day_change == D("100")
    assert v.day_change_pct == D("100") / D("10000") * 100


@pytest.mark.unit
def test_an_empty_portfolio_has_no_day_change_percentage() -> None:
    from app.domain.portfolio import valuation

    v = valuation(replay([]), {})
    assert v.total_value == 0 and v.day_change_pct is None and v.holdings == []
