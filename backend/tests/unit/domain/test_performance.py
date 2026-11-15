from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.performance import EMPTY, performance, week_start
from app.domain.portfolio import Entry

THU, FRI = date(2026, 10, 29), date(2026, 10, 30)
MON, TUE = date(2026, 11, 2), date(2026, 11, 3)
SPY = {THU: D("396"), FRI: D("400"), MON: D("404"), TUE: D("408")}


def deposit(amount: str, day: date = MON) -> Entry:
    return Entry(day, "DEPOSIT", amount=D(amount))


def withdraw(amount: str, day: date) -> Entry:
    return Entry(day, "WITHDRAW", amount=D(amount))


def buy(symbol: str, shares: str, price: str, fee: str = "0", day: date = MON) -> Entry:
    return Entry(day, "BUY", symbol, D(shares), D(price), D(fee))


def run(entries: list[Entry], closes: dict, today: date = TUE):  # type: ignore[no-untyped-def]
    return performance(entries, {"SPY": SPY, **closes}, SPY, "SPY", today)


def indexes(p) -> list[D]:  # type: ignore[no-untyped-def]
    return [round(v.index, 6) for v in p.series]


@pytest.mark.unit
def test_no_entries_no_performance() -> None:
    p = run([], {})
    assert p == EMPTY and p.total_return_pct is None and p.benchmark_return_pct is None


@pytest.mark.unit
def test_a_deposit_is_not_a_gain() -> None:
    entries = [deposit("1000"), buy("X", "10", "100"), deposit("500", TUE)]
    p = run(entries, {"X": {MON: D("100"), TUE: D("110")}})
    assert [v.value for v in p.series] == [D("1000"), D("1600")]
    assert [v.flow for v in p.series] == [D("1000"), D("500")]
    assert indexes(p) == [D(1), D("1.1")]  # the 1000 made 10%; the 500 came at the close
    assert p.total_return_pct == D("10")


@pytest.mark.unit
def test_shares_transferred_in_count_at_the_market_price_not_their_old_cost() -> None:
    entries = [Entry(MON, "TRANSFER_IN", "X", D("10"), D("50"))]
    p = run(entries, {"X": {MON: D("100"), TUE: D("105")}})
    assert p.series[0].flow == D("1000")
    assert indexes(p) == [D(1), D("1.05")]


@pytest.mark.unit
def test_the_first_days_fees_count_against_the_return() -> None:
    p = run([deposit("1000"), buy("X", "9", "100", fee="10")], {"X": {MON: D("100")}}, MON)
    assert indexes(p) == [D("0.99")]


@pytest.mark.unit
def test_taking_everything_out_and_starting_again_is_not_a_loss() -> None:
    entries = [deposit("1000", FRI), withdraw("1000", MON), deposit("500", TUE)]
    p = run(entries, {})
    assert [v.value for v in p.series] == [D("1000"), D("0"), D("500")]
    assert indexes(p) == [D(1), D(1), D(1)]


@pytest.mark.unit
def test_the_benchmark_starts_from_its_close_before_the_first_entry() -> None:
    p = run([deposit("1000")], {})
    assert [v.benchmark for v in p.series] == [D("1.01"), D("1.02")]  # from Friday's 400
    assert p.benchmark_return_pct == D("2")


@pytest.mark.unit
def test_a_symbol_without_a_close_is_valued_at_the_price_it_came_in_at() -> None:
    p = run([deposit("1000"), buy("NEW", "4", "25")], {}, MON)
    assert p.series[0].value == D("1000")


@pytest.mark.unit
def test_the_week_and_its_movers() -> None:
    entries = [
        deposit("3000", THU),
        buy("A", "10", "100", day=THU),
        buy("B", "10", "100", day=THU),
        buy("C", "10", "100", day=THU),
    ]
    flat = {THU: D("100"), FRI: D("100")}
    closes = {
        "A": {**flat, TUE: D("120")},  # no close on Monday: Friday's carries over
        "B": {**flat, TUE: D("90")},
        "C": {**flat, TUE: D("100")},
    }
    p = run(entries, closes)
    assert p.week_start == FRI
    assert p.week_change == D("100")
    assert round(p.week_change_pct, 4) == round(D(100) / D(3000) * 100, 4)
    assert [(m.symbol, m.change, m.change_pct) for m in p.gainers] == [("A", D("200"), D("20"))]
    assert [(m.symbol, m.change, m.change_pct) for m in p.losers] == [("B", D("-100"), D("-10"))]


@pytest.mark.unit
def test_a_ledger_that_begins_this_week_counts_the_week_from_nothing() -> None:
    p = run([deposit("1000"), buy("X", "10", "100")], {"X": {MON: D("100"), TUE: D("103")}})
    assert p.week_start is None
    assert p.week_change == D("30") and p.week_change_pct == D("3")
    assert [m.symbol for m in p.gainers] == ["X"]  # from the price it came in at


@pytest.mark.unit
def test_the_week_starts_at_the_last_session_before_monday() -> None:
    friday_before = date(2026, 10, 23)
    sessions = [friday_before, THU, FRI, MON, TUE]
    assert week_start(sessions, TUE) == FRI
    assert week_start(sessions, MON) == FRI
    assert (
        week_start(sessions, date(2026, 11, 1)) == friday_before
    )  # a Sunday: the week just traded
