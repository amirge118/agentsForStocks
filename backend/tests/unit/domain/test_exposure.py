from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.domain import exposure
from app.domain.exposure import CASH, FUND, UNKNOWN, Call
from app.domain.portfolio import Entry, Price, replay, valuation

DAY = date(2026, 11, 2)


def held(**shares_at_price: tuple[str, str]):  # type: ignore[no-untyped-def]
    """Cash 1000 left over after buying each symbol's shares at its price (also today's)."""
    cost = sum(D(n) * D(p) for n, p in shares_at_price.values())
    entries = [Entry(DAY, "DEPOSIT", amount=cost + 1000)]
    entries += [Entry(DAY, "BUY", s, D(n), D(p)) for s, (n, p) in shares_at_price.items()]
    prices = {s: Price(D(p), D(p), DAY) for s, (_, p) in shares_at_price.items()}
    return valuation(replay(entries), prices)


@pytest.mark.unit
def test_sectors_add_up_with_cash_last_and_drift_against_a_target() -> None:
    v = held(A=("10", "300"), B=("10", "300"), C=("10", "300"))  # 3000 + 3000 + 3000 + 1000
    sectors = exposure.sectors(
        v,
        {"A": "Technology", "B": "Technology", "C": FUND},
        {"Technology": D("40"), "Energy": D("10")},
    )
    rows = {s.sector: s for s in sectors}
    assert [s.sector for s in sectors] == ["Technology", FUND, "Energy", CASH]
    assert rows["Technology"].weight == D("60") and rows["Technology"].drift == D("20")
    assert rows["Technology"].symbols == ["A", "B"]
    assert rows["Energy"].weight == 0 and rows["Energy"].drift == D("-10")  # target, not held
    assert rows[FUND].drift is None
    assert rows[CASH].weight == D("10")
    assert sum(s.weight for s in sectors) == 100 + 0


@pytest.mark.unit
def test_a_holding_with_no_sector_yet_is_grouped_apart() -> None:
    sectors = exposure.sectors(held(A=("1", "100")), {}, {})
    assert [s.sector for s in sectors] == [UNKNOWN, CASH]


@pytest.mark.unit
def test_risk_largest_cash_and_a_beta_that_ignores_missing_ones() -> None:
    v = held(A=("10", "600"), B=("10", "300"), C=("10", "100"))  # 6000, 3000, 1000; cash 1000
    r = exposure.risk(v, {"A": 1.5, "B": 0.5, "C": None}, {})
    assert r.largest == ("A", D(6000) / D(11000) * 100)
    assert r.cash_weight == D(1000) / D(11000) * 100
    assert r.beta == (D(6000) * D("1.5") + D(3000) * D("0.5")) / D(9000)  # not counting C as 0
    assert r.beta_coverage == D(90)
    assert r.together == []


@pytest.mark.unit
def test_no_beta_at_all_is_no_reading() -> None:
    r = exposure.risk(held(A=("1", "100")), {}, {})
    assert r.beta is None and r.beta_coverage == 0


def _closes(start: float, moves: list[float]) -> dict[date, D]:
    price, out = start, {}
    for i, m in enumerate([0.0, *moves]):
        price *= 1 + m
        out[DAY + timedelta(days=i)] = D(str(round(price, 6)))
    return out


@pytest.mark.unit
def test_holdings_whose_daily_returns_move_together() -> None:
    wave = [0.01 * ((-1) ** i) * (1 + i % 3) for i in range(30)]
    closes = {
        "A": _closes(100, wave),
        "B": _closes(50, [m * 1.2 for m in wave]),  # the same moves, larger
        "C": _closes(80, [-m for m in wave]),  # the opposite
        "D": _closes(10, wave[:10]),  # too short a history
        "E": _closes(10, [0.0] * 30),  # flat: no reading
    }
    pairs = exposure.together(["A", "B", "C", "D", "E"], closes)
    assert [(p.first, p.second) for p in pairs] == [("A", "B")]
    assert pairs[0].correlation == pytest.approx(1.0) and pairs[0].sessions == 30


@pytest.mark.unit
def test_the_share_under_each_action_and_the_calls_that_changed() -> None:
    v = held(A=("10", "400"), B=("10", "300"), C=("10", "200"), D=("10", "100"))  # cash 1000
    calls = {
        "A": Call("A", "SELL", DAY, "HOLD"),
        "B": Call("B", "BUY", DAY, "BUY"),
        "C": Call("C", "HOLD", DAY, None),
    }
    shares = exposure.actions(v, calls)
    assert [(a.action, a.symbols) for a in shares] == [
        ("BUY", ["B"]),
        ("HOLD", ["C"]),
        ("SELL", ["A"]),
        (UNKNOWN, ["D"]),
    ]
    assert shares[2].weight == D(4000) / D(11000) * 100
    assert [c.symbol for c in exposure.changed(calls)] == ["A"]
