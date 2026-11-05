from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from app.agents.base import neutral_fallback
from app.agents.catalog import load_agents
from app.agents.refresh import DEFAULTS, RefreshBook, RefreshPolicy, latest_report, reusable
from app.agents.registry import registry
from app.agents.runner import AgentRunner
from app.knowledge.store import NullKnowledgeStore
from app.models.agent_result import AgentResult
from app.models.agent_run import AgentRun
from app.providers.yahoo_statements import holder_rows
from tests.factories import FakeLLM, make_context

DAY = date(2026, 8, 3)
GOOD = {"signal": "bullish", "confidence": 80.0, "data_gaps": []}
POLICY = RefreshPolicy(max_age_days=90, on_new_report=True)


@pytest.mark.unit
def test_every_agent_has_a_policy_in_the_table() -> None:
    assert set(DEFAULTS) == set(load_agents().names())


@pytest.mark.unit
def test_a_config_overrides_one_setting_and_rejects_typos() -> None:
    book = RefreshBook.from_config('{"moat": {"max_age_days": 7}}')
    assert book.resolve("moat") == RefreshPolicy(7, on_new_report=True)
    assert book.resolve("technicals") == RefreshPolicy()
    with pytest.raises(ValueError, match="max_days"):
        RefreshBook({"moat": {"max_days": 7}})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "age", "expected"),
    [
        (GOOD, 90, True),
        (GOOD, 91, False),
        ({**GOOD, "needs_review": ["model down"]}, 1, False),
        ({"signal": "neutral", "confidence": 0.0, "data_gaps": ["income"]}, 1, False),
        ({"signal": "neutral", "confidence": 0.0, "data_gaps": []}, 1, True),
        ({"signal": "bullish", "confidence": 60.0, "data_gaps": ["estimates"]}, 1, True),
    ],
)
def test_what_stays_good(result: dict, age: int, expected: bool) -> None:
    assert reusable(POLICY, result, DAY, DAY + timedelta(days=age)) is expected


@pytest.mark.unit
def test_a_daily_agent_is_never_reused() -> None:
    assert not reusable(RefreshPolicy(), GOOD, DAY, DAY + timedelta(days=1))


@pytest.mark.unit
def test_the_latest_report_ignores_the_coming_one() -> None:
    rows = [
        {"date": "2026-11-20", "epsActual": None},
        {"date": "2026-08-01", "epsActual": 1.0},
        {"date": "2026-05-01", "epsActual": 0.9},
    ]
    assert latest_report(rows) == date(2026, 8, 1)
    assert latest_report([]) is None


def _agent(llm: FakeLLM, fetched: list[str]):
    agent = registry.get("fundamentals").agent_cls(make_context(llm=llm))
    original = agent.fetch

    async def counting(symbol: str, run_date: date):
        fetched.append(symbol)
        return await original(symbol, run_date)

    agent.fetch = counting
    return agent


async def _days_of(session_factory) -> list[str | None]:
    async with session_factory() as session:
        rows = await session.scalars(select(AgentResult).order_by(AgentResult.run_date))
        return [row.result_json.get("reused_from") for row in rows]


@pytest.mark.unit
async def test_within_its_window_the_agent_doesnt_run_at_all(session_factory) -> None:
    llm, fetched = FakeLLM(), []
    agent = _agent(llm, fetched)
    runner = AgentRunner(session_factory, NullKnowledgeStore())

    assert (await runner.run(agent, "AAPL", DAY)).status == "completed"
    next_day = await runner.run(agent, "AAPL", DAY + timedelta(days=1))

    assert next_day.status == "reused"
    assert next_day.result is not None and next_day.result.reused_from == DAY.isoformat()
    assert len(fetched) == 1 and len(llm.calls) == 1  # no data fetched, no model call

    later = await runner.run(agent, "AAPL", DAY + timedelta(days=2))
    assert later.result is not None and later.result.reused_from == DAY.isoformat()  # the source
    assert await _days_of(session_factory) == [None, DAY.isoformat(), DAY.isoformat()]

    async with session_factory() as session:
        statuses = await session.scalars(select(AgentRun.status).order_by(AgentRun.started_at))
        assert list(statuses) == ["completed", "reused", "reused"]


@pytest.mark.unit
async def test_age_is_counted_from_the_real_run_not_from_the_last_copy(session_factory) -> None:
    llm, fetched = FakeLLM(), []
    agent = _agent(llm, fetched)  # fundamentals: 7 days
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    await runner.run(agent, "AAPL", DAY)
    for days in (3, 6):
        assert (await runner.run(agent, "AAPL", DAY + timedelta(days=days))).status == "reused"
    assert (await runner.run(agent, "AAPL", DAY + timedelta(days=9))).status == "completed"
    assert len(fetched) == 2


@pytest.mark.unit
async def test_force_a_new_report_and_another_symbol_all_run(session_factory) -> None:
    llm, fetched = FakeLLM(), []
    agent = _agent(llm, fetched)
    tomorrow = DAY + timedelta(days=1)

    async def reported(symbol: str) -> date | None:
        return tomorrow

    plain = AgentRunner(session_factory, NullKnowledgeStore())
    await plain.run(agent, "AAPL", DAY)
    assert (await plain.run(agent, "MSFT", tomorrow)).status == "completed"

    with_report = AgentRunner(session_factory, NullKnowledgeStore(), reported=reported)
    assert (await with_report.run(agent, "AAPL", tomorrow)).status == "completed"

    day_after = tomorrow + timedelta(days=1)
    forced = await plain.run(agent, "AAPL", day_after, force=True)
    assert forced.status == "completed"
    assert forced.result is not None and forced.result.reused_from is None


@pytest.mark.unit
async def test_a_failed_report_check_doesnt_stop_the_reuse(session_factory) -> None:
    async def down(symbol: str) -> date | None:
        raise RuntimeError("Yahoo is down")

    agent = _agent(FakeLLM(), [])
    runner = AgentRunner(session_factory, NullKnowledgeStore(), reported=down)
    await runner.run(agent, "AAPL", DAY)
    assert (await runner.run(agent, "AAPL", DAY + timedelta(days=1))).status == "reused"


@pytest.mark.unit
async def test_a_result_that_fell_back_runs_again_the_next_day(session_factory) -> None:
    fetched: list[str] = []
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    await runner.run(_agent(FakeLLM(fail=True), fetched), "AAPL", DAY)
    outcome = await runner.run(_agent(FakeLLM(), fetched), "AAPL", DAY + timedelta(days=1))
    assert outcome.status == "completed"
    assert len(fetched) == 2
    assert neutral_fallback().confidence == 0


@pytest.mark.unit
def test_yahoo_holders_become_share_changes_and_old_filings_are_dropped() -> None:
    frame = pd.DataFrame(
        {
            "Date Reported": pd.to_datetime(["2026-06-30", "2026-06-30", "2023-12-31"]),
            "Holder": ["Blackrock Inc. ", "Vanguard", "Old Fund"],
            "Shares": [110, 50, 999],
            "pctChange": [0.10, float("nan"), 0.5],
        }
    )
    rows = holder_rows(frame, date(2026, 11, 4))
    assert [r["holder"] for r in rows] == ["Blackrock Inc.", "Vanguard"]
    assert rows[0]["shares"] == 110.0 and rows[0]["change"] == pytest.approx(10.0)
    assert "change" not in rows[1]  # unknown, not 0
    assert holder_rows(None, date(2026, 11, 4)) == []
