from datetime import date

import pytest
from sqlalchemy import select

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.runner import AgentRunner, SessionResultsReader
from app.core.context import current_usage
from app.knowledge.store import Learning
from app.models.agent_result import AgentResult
from app.models.agent_run import AgentRun
from app.repositories.agent_results import AgentResultRepository
from tests.factories import FakeLLM, make_context

RUN_DATE = date(2026, 10, 23)


class _Result(AnalysisResult):
    score: float


class _StubAgent(Agent[dict, _Result]):
    name = "stub"
    result_model = _Result

    def __init__(
        self, ctx, *, fail_on: str | None = None, signal: str = "bullish", reasoning: str = "r"
    ) -> None:
        super().__init__(ctx)
        self.fail_on = fail_on
        self.signal = signal
        self.reasoning = reasoning
        self.memory_seen: list[str] | None = None
        self.fetches = 0

    async def fetch(self, symbol: str, run_date: date) -> dict:
        self.fetches += 1
        if self.fail_on == "fetch":
            raise RuntimeError("provider down")
        return {"score": 1.5}

    async def analyze(self, symbol: str, data: dict, memory: list[str]) -> _Result:
        self.memory_seen = memory
        return _Result(
            signal=self.signal,
            confidence=60,
            reasoning=self.reasoning,
            summary=f"stub summary — {self.reasoning}" if self.reasoning != "r" else "stub summary",
            score=data["score"],
        )

    def learnings(self, symbol: str, result: _Result) -> list[Learning]:
        return [*super().learnings(symbol, result), Learning(kind="pattern", content="p")]


class _RecordingKnowledge:
    def __init__(self, fail: bool = False) -> None:
        self.stored: list[Learning] = []

    async def recall(self, symbol: str, agent_type: str) -> list[str]:
        return [f"memory for {symbol}/{agent_type}"]

    async def store(self, symbol: str, agent_type: str, learning: Learning) -> None:
        self.stored.append(learning)


@pytest.mark.unit
async def test_run_persists_result_and_learnings(session_factory, db_session) -> None:
    knowledge = _RecordingKnowledge()
    agent = _StubAgent(make_context())
    outcome = await AgentRunner(session_factory, knowledge).run(agent, "AAPL", RUN_DATE)

    assert outcome.status == "completed"
    assert agent.memory_seen == ["memory for AAPL/stub"]
    row = (await db_session.execute(select(AgentResult))).scalar_one()
    assert row.result_json == {
        "signal": "bullish",
        "confidence": 60.0,
        "reasoning": "r",
        "summary": "stub summary",
        "score": 1.5,
        "compliance": {"status": "pass", "findings": [], "original_reasoning": None},
    }
    assert row.run_id == outcome.run_id
    assert [lr.kind for lr in knowledge.stored] == ["case", "pattern"]


@pytest.mark.unit
async def test_promissory_reasoning_is_replaced_before_storage_and_learnings(
    session_factory, db_session
) -> None:
    knowledge = _RecordingKnowledge()
    text = "Guaranteed upside from here."
    agent = _StubAgent(make_context(), reasoning=text)

    outcome = await AgentRunner(session_factory, knowledge).run(agent, "AAPL", RUN_DATE)

    row = (await db_session.execute(select(AgentResult))).scalar_one()
    stored = row.result_json
    assert stored["compliance"]["status"] == "fail"
    assert stored["compliance"]["original_reasoning"] == text
    assert "Guaranteed" not in stored["reasoning"]
    assert "Guaranteed" not in stored["summary"]
    assert outcome.result is not None and outcome.result.reasoning == stored["reasoning"]
    # The knowledge base only ever sees the reviewed text
    assert all("Guaranteed" not in lr.content for lr in knowledge.stored)


@pytest.mark.unit
async def test_second_run_same_day_is_skipped_unless_forced(session_factory, db_session) -> None:
    runner = AgentRunner(session_factory, _RecordingKnowledge())
    agent = _StubAgent(make_context())

    assert (await runner.run(agent, "AAPL", RUN_DATE)).status == "completed"
    assert (await runner.run(agent, "AAPL", RUN_DATE)).status == "skipped"
    assert agent.fetches == 1

    agent.signal = "bearish"
    assert (await runner.run(agent, "AAPL", RUN_DATE, force=True)).status == "completed"
    rows = (await db_session.execute(select(AgentResult))).scalars().all()
    assert len(rows) == 1  # forced re-run replaced the row
    await db_session.refresh(rows[0])
    assert rows[0].result_json["signal"] == "bearish"


@pytest.mark.unit
async def test_failure_is_reported_not_raised_and_nothing_stored(
    session_factory, db_session
) -> None:
    knowledge = _RecordingKnowledge()
    outcome = await AgentRunner(session_factory, knowledge).run(
        _StubAgent(make_context(), fail_on="fetch"), "AAPL", RUN_DATE
    )
    assert outcome.status == "failed"
    assert "provider down" in outcome.error
    assert (await db_session.execute(select(AgentResult))).first() is None
    assert knowledge.stored == []


@pytest.mark.unit
async def test_session_results_reader(session_factory, db_session) -> None:
    repo = AgentResultRepository(db_session)
    await repo.upsert(
        agent_type="moat", symbol="AAPL", run_date=RUN_DATE, run_id="r", result={"a": 1}
    )
    await db_session.commit()
    reader = SessionResultsReader(session_factory)
    assert await reader.get_for_date("AAPL", RUN_DATE, ["moat", "risk"]) == {"moat": {"a": 1}}


@pytest.mark.unit
async def test_every_outcome_is_recorded_in_agent_runs(session_factory, db_session) -> None:
    runner = AgentRunner(session_factory, _RecordingKnowledge())
    await runner.run(_StubAgent(make_context()), "AAPL", RUN_DATE, pipeline_run_id="p1")
    await runner.run(_StubAgent(make_context()), "AAPL", RUN_DATE, pipeline_run_id="p1")
    await runner.run(_StubAgent(make_context(), fail_on="fetch"), "MSFT", RUN_DATE)

    runs = (
        (await db_session.execute(select(AgentRun).order_by(AgentRun.started_at))).scalars().all()
    )
    assert [(r.symbol, r.status) for r in runs] == [
        ("AAPL", "completed"),
        ("AAPL", "skipped"),
        ("MSFT", "failed"),
    ]
    assert runs[0].pipeline_run_id == "p1"
    assert runs[2].error == "provider down"
    assert all(r.finished_at >= r.started_at for r in runs)


@pytest.mark.unit
async def test_database_outage_is_reported_not_raised() -> None:
    def broken_session_factory():
        raise RuntimeError("db gone")

    runner = AgentRunner(broken_session_factory, _RecordingKnowledge())
    outcome = await runner.run(_StubAgent(make_context()), "AAPL", RUN_DATE)
    assert outcome.status == "failed"
    assert "db gone" in outcome.error  # the audit write failed too, but was only logged


class _LLMStubAgent(_StubAgent):
    """Calls the (fake) LLM through judge(), like the real agents do."""

    async def analyze(self, symbol: str, data: dict, memory: list[str]) -> _Result:
        judgement = await self.judge(
            "prompt", fallback=quant_fallback("neutral", 10, "quant"), prompt_name="technicals"
        )
        return _Result(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            summary="s",
            score=data["score"],
        )


class _UsageLLM(FakeLLM):
    """FakeLLM that also reports usage the way LLMClient does."""

    async def generate(self, **kwargs):
        usage = current_usage()
        if usage is not None and not self.fail:
            usage.llm_calls += 1
            usage.input_tokens += 1500
            usage.output_tokens += 90
            usage.cost_usd += 0.002
        return await super().generate(**kwargs)


@pytest.mark.unit
async def test_agent_run_records_timings_and_llm_usage(session_factory, db_session) -> None:
    agent = _LLMStubAgent(make_context(llm=_UsageLLM()), reasoning="x")
    outcome = await AgentRunner(session_factory, _RecordingKnowledge()).run(
        agent, "AAPL", RUN_DATE, pipeline_run_id="p1"
    )
    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert (run.llm_calls, run.input_tokens, run.output_tokens) == (1, 1500, 90)
    assert run.cost_usd == pytest.approx(0.002)
    assert run.llm_fallbacks == 0
    assert run.fetch_ms is not None and run.analyze_ms is not None
    assert outcome.usage is not None and outcome.usage.llm_calls == 1


@pytest.mark.unit
async def test_llm_fallback_is_counted(session_factory, db_session) -> None:
    agent = _LLMStubAgent(make_context(llm=FakeLLM(fail=True)), reasoning="x")
    outcome = await AgentRunner(session_factory, _RecordingKnowledge()).run(agent, "AAPL", RUN_DATE)
    assert outcome.result is not None and outcome.result.signal == "neutral"
    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert (run.llm_fallbacks, run.llm_calls) == (1, 0)


@pytest.mark.unit
async def test_run_logs_carry_the_run_context(session_factory, caplog) -> None:
    import logging

    from app.core.logging import ContextFilter

    caplog.handler.addFilter(ContextFilter())
    caplog.set_level(logging.INFO, logger="app.agents.runner")
    outcome = await AgentRunner(session_factory, _RecordingKnowledge()).run(
        _StubAgent(make_context()), "AAPL", RUN_DATE, pipeline_run_id="p1"
    )
    records = [r for r in caplog.records if r.name == "app.agents.runner"]
    assert [r.message for r in records] == ["Agent run started", "Agent run completed"]
    for record in records:
        assert (record.run_id, record.pipeline_run_id) == (outcome.run_id, "p1")
        assert (record.agent, record.symbol) == ("stub", "AAPL")
    assert records[-1].duration_ms >= 0
