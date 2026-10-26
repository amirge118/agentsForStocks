"""
OutcomeReviewAgent (lessons from settled recommendations) and the track record the
recommendation agent reads back — point-in-time, through the runner and the DB.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.agents.catalog import load_agents
from app.agents.outcome_review import (
    REVIEW_LIMIT,
    OutcomeReviewAgent,
    SessionOutcomesReader,
)
from app.agents.recommendation import RecommendationAgent
from app.agents.runner import AgentRunner, SessionResultsReader
from app.knowledge.store import Learning, NullKnowledgeStore
from app.models.agent_result import AgentResult
from app.models.decision_outcome import DecisionOutcome
from app.repositories.agent_results import AgentResultRepository
from tests.factories import FakeLLM, FakeOutcomes, FakeResults, lesson, make_context, settled_call

RUN_DATE = date(2026, 10, 23)
registry = load_agents()


class _Knowledge(NullKnowledgeStore):
    def __init__(self) -> None:
        self.stored: list[Learning] = []

    async def store(self, symbol: str, agent_type: str, learning: Learning) -> None:
        self.stored.append(learning)


def _review(llm: FakeLLM, outcomes: FakeOutcomes) -> OutcomeReviewAgent:
    return OutcomeReviewAgent(make_context(llm=llm, outcomes=outcomes))


async def _stored(db_session, agent: str = "outcome_review") -> dict:
    stmt = select(AgentResult).where(AgentResult.agent_type == agent)
    return (await db_session.execute(stmt)).scalar_one().result_json


@pytest.mark.unit
async def test_settled_calls_become_stored_lessons(session_factory, db_session) -> None:
    llm = FakeLLM()
    knowledge = _Knowledge()
    outcomes = FakeOutcomes(calls=[settled_call()], lessons=[])

    outcome = await AgentRunner(session_factory, knowledge).run(
        _review(llm, outcomes), "AAPL", RUN_DATE
    )

    assert outcome.status == "completed"
    stored = await _stored(db_session)
    assert (stored["signal"], stored["confidence"]) == ("neutral", 0.0)
    assert stored["data_gaps"] == [] and stored["contract_violations"] == []
    [saved] = stored["lessons"]
    assert saved["decision_date"] == "2026-09-01"
    assert (saved["signal"], saved["alpha"], saved["hit"]) == ("bullish", 0.015, True)
    assert saved["text"].startswith("Alpha +1.5%")
    assert "Reviewed 1 settled call, 1 right: 2026-09-01 bullish +1.5%" in stored["reasoning"]
    # One model call, labelled for the ledger, with the outcome in the prompt
    [call] = llm.calls
    assert call["prompt_name"] == "outcome_review"
    assert "Alpha: +1.5%" in call["prompt"] and "Benchmark (SPY) return: +0.1%" in call["prompt"]
    assert "right" in call["prompt"]
    # The lesson is remembered as a pattern, not the summary as a case
    assert [(k.kind, k.tags) for k in knowledge.stored] == [("pattern", ("lesson",))]


@pytest.mark.unit
async def test_reads_only_what_was_known_before_the_run(session_factory) -> None:
    outcomes = FakeOutcomes(calls=[settled_call(exit_date=RUN_DATE)], lessons=[])
    llm = FakeLLM()
    await AgentRunner(session_factory, NullKnowledgeStore()).run(
        _review(llm, outcomes), "AAPL", RUN_DATE
    )
    # Outcomes closed before today; reviews from earlier days (a rerun redoes today's)
    assert outcomes.asked == [("calls", RUN_DATE), ("lessons", RUN_DATE - timedelta(days=1))]
    assert llm.calls == []  # the window closed today: not yet known


@pytest.mark.unit
async def test_reviewed_calls_are_skipped_and_a_quiet_day_is_not_a_data_gap(
    session_factory, db_session
) -> None:
    done = lesson(symbol="AAPL", decision_date=date(2026, 9, 1))
    llm = FakeLLM()
    await AgentRunner(session_factory, NullKnowledgeStore()).run(
        _review(llm, FakeOutcomes(calls=[settled_call()], lessons=[done])), "AAPL", RUN_DATE
    )
    stored = await _stored(db_session)
    assert llm.calls == []
    assert stored["lessons"] == [] and stored["data_gaps"] == []
    assert stored["reasoning"] == "No newly settled recommendations to review"


@pytest.mark.unit
async def test_backlog_is_worked_off_oldest_first() -> None:
    calls = [settled_call(decision_date=date(2026, 9, d)) for d in (10, 1, 7, 3, 4)]
    agent = _review(FakeLLM(), FakeOutcomes(calls=calls, lessons=[]))
    backlog = await agent.fetch("AAPL", RUN_DATE)
    assert [c.decision_date.day for c in backlog.calls] == [1, 3, 4][:REVIEW_LIMIT]


@pytest.mark.unit
async def test_without_the_model_the_lesson_is_the_bare_outcome(
    session_factory, db_session
) -> None:
    call = settled_call(signal="bearish", alpha=0.021, raw_return=0.03)
    await AgentRunner(session_factory, NullKnowledgeStore()).run(
        _review(FakeLLM(fail=True), FakeOutcomes(calls=[call], lessons=[])), "AAPL", RUN_DATE
    )
    [saved] = (await _stored(db_session))["lessons"]
    assert saved["hit"] is False
    assert saved["text"] == "Alpha +2.1% vs SPY over 20 trading days; the bearish call was wrong."


@pytest.mark.unit
async def test_a_lesson_that_does_not_quote_its_alpha_breaks_the_contract(
    session_factory, db_session
) -> None:
    llm = FakeLLM(reply={"lesson": "The call worked out fine."})
    await AgentRunner(session_factory, NullKnowledgeStore()).run(
        _review(llm, FakeOutcomes(calls=[settled_call()], lessons=[])), "AAPL", RUN_DATE
    )
    stored = await _stored(db_session)
    assert stored["contract_violations"] == ["lessons that don't quote their alpha: 2026-09-01"]


@pytest.mark.unit
async def test_neutral_call_prompt_states_the_band() -> None:
    llm = FakeLLM()
    agent = _review(llm, FakeOutcomes(calls=[settled_call(signal="neutral")], lessons=[]))
    await agent.analyze("AAPL", await agent.fetch("AAPL", RUN_DATE), [])
    assert "a neutral call needs alpha within ±2.0%" in llm.calls[0]["prompt"]


# ------------------------------------------------------------- recommendation


def _analysts() -> FakeResults:
    return FakeResults(
        {
            n: {"signal": "bullish", "confidence": 70.0, "reasoning": "ok"}
            for n in registry.weights()
        }
    )


@pytest.mark.unit
async def test_recommendation_prompt_carries_the_track_record() -> None:
    outcomes = FakeOutcomes(
        calls=[settled_call(), settled_call(decision_date=date(2026, 8, 1), alpha=-0.04)],
        lessons=[lesson(symbol="AAPL"), lesson()],
    )
    llm = FakeLLM()
    agent = RecommendationAgent(make_context(llm=llm, results=_analysts(), outcomes=outcomes))
    data = await agent.fetch("AAPL", RUN_DATE)
    await agent.analyze("AAPL", data, [])

    prompt = llm.calls[0]["prompt"]
    assert "for AAPL (20 trading days later, vs SPY)" in prompt
    assert "2 settled calls, 1 right (50%), mean alpha captured -1.2%" in prompt
    assert "- AAPL 2026-08-03 bearish, alpha +2.1%" in prompt
    assert "- MSFT 2026-08-03 bearish, alpha +2.1%" in prompt
    # Point-in-time: outcomes known before the run, lessons written up to it
    assert ("calls", RUN_DATE) in outcomes.asked and ("lessons", RUN_DATE) in outcomes.asked


@pytest.mark.unit
async def test_new_symbol_has_no_track_record_and_no_data_gap(session_factory) -> None:
    llm = FakeLLM()
    agent = RecommendationAgent(make_context(llm=llm, results=_analysts()))
    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)
    assert outcome.result is not None and outcome.result.data_gaps == []
    assert "Track record: no settled recommendations yet." in llm.calls[0]["prompt"]


# ------------------------------------------------------------- the real reader


async def _seed(session_factory) -> None:
    """Two settled AAPL recommendations (one closed only today) and stored reviews."""
    async with session_factory() as session:
        results = AgentResultRepository(session)
        for day, signal in ((date(2026, 9, 1), "bullish"), (date(2026, 9, 22), "bearish")):
            await results.upsert(
                agent_type="recommendation",
                symbol="AAPL",
                run_date=day,
                run_id="r",
                result={"signal": signal, "confidence": 60.0, "reasoning": f"why {day}"},
            )
        session.add_all(
            [
                DecisionOutcome(
                    symbol="AAPL",
                    decision_date=day,
                    horizon_days=20,
                    benchmark="SPY",
                    status="settled",
                    entry_date=day + timedelta(days=1),
                    exit_date=exit_,
                    raw_return=0.02,
                    alpha=alpha,
                )
                for day, exit_, alpha in (
                    (date(2026, 9, 1), date(2026, 9, 30), 0.01),
                    (date(2026, 9, 22), RUN_DATE, -0.03),
                )
            ]
        )
        for symbol, day, decided in (
            ("AAPL", date(2026, 10, 1), (date(2026, 8, 3), date(2026, 8, 4))),
            ("MSFT", date(2026, 10, 2), (date(2026, 8, 5),)),
            ("MSFT", RUN_DATE + timedelta(days=1), (date(2026, 9, 2),)),  # from the future
        ):
            await results.upsert(
                agent_type="outcome_review",
                symbol=symbol,
                run_date=day,
                run_id="r",
                result={
                    "lessons": [
                        {
                            "decision_date": d.isoformat(),
                            "signal": "bullish",
                            "alpha": 0.01,
                            "text": f"{symbol} {d}",
                        }
                        for d in decided
                    ]
                },
            )
        await session.commit()


@pytest.mark.unit
async def test_session_reader_is_point_in_time(session_factory) -> None:
    await _seed(session_factory)
    reader = SessionOutcomesReader(session_factory)

    calls = await reader.settled_calls(
        "AAPL", agent="recommendation", horizon=20, before=RUN_DATE, limit=10
    )
    assert [(c.decision_date, c.signal, c.alpha, c.reasoning) for c in calls] == [
        (date(2026, 9, 1), "bullish", 0.01, "why 2026-09-01")
    ]
    later = await reader.settled_calls(
        "AAPL", agent="recommendation", horizon=20, before=RUN_DATE + timedelta(days=1), limit=10
    )
    assert [c.decision_date for c in later] == [date(2026, 9, 22), date(2026, 9, 1)]
    assert not await reader.settled_calls(
        "AAPL", agent="recommendation", horizon=5, before=RUN_DATE, limit=10
    )

    mine = await reader.lessons(until=RUN_DATE, symbol="AAPL")
    assert [lsn.decision_date for lsn in mine] == [date(2026, 8, 4), date(2026, 8, 3)]
    others = await reader.lessons(until=RUN_DATE, exclude_symbol="AAPL")
    assert [lsn.text for lsn in others] == ["MSFT 2026-08-05"]  # not the one from tomorrow
    assert len(await reader.lessons(until=RUN_DATE, limit=1)) == 1


@pytest.mark.unit
async def test_todays_lesson_reaches_todays_recommendation(session_factory) -> None:
    """outcome_review runs first (dependency), so the recommendation reads its lesson."""
    await _seed(session_factory)
    llm = FakeLLM(reply={"lesson": "Alpha +1.0% for the bullish call; margins held."})
    ctx = make_context(
        llm=llm,
        results=_analysts_in(session_factory),
        outcomes=SessionOutcomesReader(session_factory),
    )
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    assert "outcome_review" in registry.get("recommendation").depends_on

    await runner.run(OutcomeReviewAgent(ctx), "AAPL", RUN_DATE)
    await runner.run(RecommendationAgent(ctx), "AAPL", RUN_DATE)

    prompt = llm.calls[-1]["prompt"]
    assert "AAPL 2026-09-01 bullish, alpha +1.0%: Alpha +1.0% for the bullish call" in prompt
    assert "1 settled call, 1 right (100%)" in prompt


def _analysts_in(session_factory) -> SessionResultsReader:
    class _WithAnalysts(SessionResultsReader):
        async def get_for_date(self, symbol: str, run_date: date, agent_types: list[str]) -> dict:
            return await _analysts().get_for_date(symbol, run_date, agent_types)

    return _WithAnalysts(session_factory)
