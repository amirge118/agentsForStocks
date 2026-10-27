import logging
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select

from app.models.decision_outcome import DecisionOutcome
from app.pipeline.settlement import OutcomeSettler, SettlementReport
from app.providers.errors import ProviderError
from app.repositories.agent_results import AgentResultRepository

# Mon 2026-10-05 … Fri 2026-10-16: ten sessions
SESSIONS = pd.bdate_range("2026-10-05", periods=10, tz="America/New_York")


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=SESSIONS[: len(values)])


class FakePrices:
    def __init__(self, closes: dict[str, pd.Series], broken: set[str] | None = None) -> None:
        self.closes = closes
        self.broken = broken or set()
        self.calls: list[tuple[str, date, date]] = []

    async def get_closes(self, symbol: str, start: date, end: date) -> pd.Series:
        self.calls.append((symbol, start, end))
        if symbol in self.broken:
            raise ProviderError(f"{symbol} down")
        # Like Yahoo, may hand back more than asked: the settler must cut at `end`
        return self.closes.get(symbol, pd.Series(dtype=float))


PRICES = {
    "AAPL": series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109]),
    "MSFT": series([200, 200, 198, 196, 194, 192, 190, 188, 186, 184]),
    "SPY": series([50, 50, 50.5, 50.5, 51, 51, 51.5, 51.5, 52, 52]),
}


async def add_results(session_factory, *decisions: tuple[str, date, str]) -> None:
    async with session_factory() as session:
        repo = AgentResultRepository(session)
        for symbol, run_date, agent in decisions:
            await repo.upsert(
                agent_type=agent, symbol=symbol, run_date=run_date, run_id="r", result={}
            )
        await session.commit()


async def outcomes(session_factory) -> dict[tuple[str, date, int], DecisionOutcome]:
    async with session_factory() as session:
        rows = (await session.execute(select(DecisionOutcome))).scalars().all()
    return {(r.symbol, r.decision_date, r.horizon_days): r for r in rows}


def settler(session_factory, prices: FakePrices, **kwargs) -> OutcomeSettler:
    return OutcomeSettler(session_factory, prices, horizons=(2, 5), **kwargs)


@pytest.mark.unit
async def test_backfills_and_settles_every_judged_day(session_factory) -> None:
    await add_results(
        session_factory,
        ("AAPL", date(2026, 10, 5), "risk"),
        ("AAPL", date(2026, 10, 5), "recommendation"),  # same day: one decision
        ("AAPL", date(2026, 10, 6), "risk"),
        ("MSFT", date(2026, 10, 5), "risk"),
    )
    report = await settler(session_factory, FakePrices(PRICES)).settle(as_of=date(2026, 10, 19))

    assert (report.seeded, report.settled, report.pending, report.unavailable) == (6, 6, 0, 0)
    rows = await outcomes(session_factory)
    aapl = rows[("AAPL", date(2026, 10, 5), 5)]
    assert aapl.status == "settled" and aapl.benchmark == "SPY"
    assert (aapl.entry_date, aapl.exit_date) == (date(2026, 10, 6), date(2026, 10, 13))
    assert aapl.raw_return == pytest.approx(5 / 101)
    assert aapl.alpha == pytest.approx(5 / 101 - 1.5 / 50)
    assert aapl.settled_at is not None
    assert rows[("MSFT", date(2026, 10, 5), 2)].alpha < 0


@pytest.mark.unit
async def test_rerun_is_a_no_op(session_factory) -> None:
    await add_results(session_factory, ("AAPL", date(2026, 10, 5), "risk"))
    prices = FakePrices(PRICES)
    await settler(session_factory, prices).settle(as_of=date(2026, 10, 19))
    first = await outcomes(session_factory)
    prices.calls.clear()

    report = await settler(session_factory, prices).settle(as_of=date(2026, 10, 19))

    assert (report.seeded, report.settled, report.pending) == (0, 0, 0)
    assert prices.calls == []
    assert {k: r.settled_at for k, r in (await outcomes(session_factory)).items()} == {
        k: r.settled_at for k, r in first.items()
    }


@pytest.mark.unit
async def test_running_window_stays_pending_and_todays_bar_is_ignored(session_factory) -> None:
    await add_results(session_factory, ("AAPL", date(2026, 10, 9), "risk"))
    # Closes through Fri 10-16 exist, but as of Thu 10-15 only Mon-Wed have closed
    report = await settler(session_factory, FakePrices(PRICES)).settle(as_of=date(2026, 10, 15))

    assert (report.settled, report.pending) == (1, 1)  # +2 settled, +5 still running
    rows = await outcomes(session_factory)
    assert rows[("AAPL", date(2026, 10, 9), 2)].exit_date == date(2026, 10, 14)
    running = rows[("AAPL", date(2026, 10, 9), 5)]
    assert (running.status, running.attempts) == ("pending", 0)


@pytest.mark.unit
async def test_decisions_on_or_after_as_of_are_left_alone(session_factory) -> None:
    await add_results(session_factory, ("AAPL", date(2026, 10, 15), "risk"))
    prices = FakePrices(PRICES)
    report = await settler(session_factory, prices).settle(as_of=date(2026, 10, 15))
    assert (report.seeded, report.settled, report.pending) == (2, 0, 0)
    assert prices.calls == []


@pytest.mark.unit
async def test_overdue_window_without_prices_becomes_unavailable(session_factory, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.pipeline.settlement")
    await add_results(
        session_factory, ("GONE", date(2026, 10, 5), "risk"), ("DOWN", date(2026, 10, 5), "risk")
    )
    prices = FakePrices(PRICES, broken={"DOWN"})
    late = date(2026, 12, 1)  # long past both windows

    first = await settler(session_factory, prices, max_attempts=2).settle(as_of=late)
    assert (first.pending, first.unavailable, first.failed_symbols) == (4, 0, ["DOWN"])
    assert {r.attempts for r in (await outcomes(session_factory)).values()} == {1}

    second = await settler(session_factory, prices, max_attempts=2).settle(as_of=late)
    assert (second.pending, second.unavailable) == (0, 4)
    assert {r.status for r in (await outcomes(session_factory)).values()} == {"unavailable"}
    assert "Outcome unavailable" in caplog.text


@pytest.mark.unit
async def test_missing_prices_before_the_window_is_due_count_no_attempt(session_factory) -> None:
    await add_results(session_factory, ("GONE", date(2026, 10, 5), "risk"))
    report = await settler(session_factory, FakePrices(PRICES)).settle(as_of=date(2026, 10, 8))
    assert report.pending == 2
    assert {r.attempts for r in (await outcomes(session_factory)).values()} == {0}


@pytest.mark.unit
async def test_benchmark_outage_leaves_everything_pending(session_factory, caplog) -> None:
    await add_results(session_factory, ("AAPL", date(2026, 10, 5), "risk"))
    prices = FakePrices(PRICES, broken={"SPY"})
    report = await settler(session_factory, prices).settle(as_of=date(2026, 12, 1))

    assert (report.settled, report.pending, report.unavailable) == (0, 2, 0)
    assert {r.attempts for r in (await outcomes(session_factory)).values()} == {0}
    assert [c[0] for c in prices.calls] == ["SPY"]
    assert "Benchmark prices unavailable" in caplog.text


@pytest.mark.unit
async def test_symbols_narrow_the_pass(session_factory) -> None:
    await add_results(
        session_factory, ("AAPL", date(2026, 10, 5), "risk"), ("MSFT", date(2026, 10, 5), "risk")
    )
    report = await settler(session_factory, FakePrices(PRICES)).settle(
        as_of=date(2026, 10, 19), symbols=["MSFT"]
    )
    assert (report.seeded, report.settled) == (2, 2)
    assert {k[0] for k in await outcomes(session_factory)} == {"MSFT"}


@pytest.mark.unit
async def test_benchmark_is_configurable(session_factory) -> None:
    await add_results(session_factory, ("AAPL", date(2026, 10, 5), "risk"))
    prices = FakePrices({**PRICES, "QQQ": PRICES["SPY"]})
    await settler(session_factory, prices, benchmark="QQQ").settle(as_of=date(2026, 10, 19))
    assert {r.benchmark for r in (await outcomes(session_factory)).values()} == {"QQQ"}
    assert prices.calls[0][0] == "QQQ"


@pytest.mark.unit
def test_report_renders_one_line() -> None:
    report = SettlementReport(
        as_of=date(2026, 10, 19), seeded=4, settled=3, pending=1, failed_symbols=["DOWN"]
    )
    assert report.render() == (
        "Outcomes as of 2026-10-19: 3 settled, 1 pending, 0 unavailable (4 new); "
        "prices unavailable for DOWN"
    )
