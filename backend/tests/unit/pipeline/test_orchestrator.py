import asyncio
from datetime import date

import pytest
from sqlalchemy import select

from app.agents.base import Agent, AnalysisResult
from app.agents.registry import AgentRegistry
from app.agents.runner import AgentRunner
from app.knowledge.store import NullKnowledgeStore
from app.models.agent_run import AgentRun
from app.pipeline.orchestrator import PipelineOrchestrator
from tests.factories import make_context

RUN_DATE = date(2026, 10, 23)


class _Tracker:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.active = 0
        self.peak = 0


def _registry(tracker: _Tracker, failing: set[str] = frozenset()) -> AgentRegistry:
    reg = AgentRegistry()

    def make(name: str, deps: tuple[str, ...] = ()) -> None:
        class _Agent(Agent[None, AnalysisResult]):
            result_model = AnalysisResult

            async def fetch(self, symbol: str, run_date: date) -> None:
                tracker.active += 1
                tracker.peak = max(tracker.peak, tracker.active)
                tracker.events.append(("start", self.name, symbol))
                await asyncio.sleep(0.01)
                tracker.active -= 1
                if self.name in failing:
                    raise RuntimeError(f"{self.name} broke")

            async def analyze(self, symbol: str, data: None, memory: list[str]) -> AnalysisResult:
                tracker.events.append(("end", self.name, symbol))
                return AnalysisResult(signal="neutral", confidence=0, reasoning="", summary="")

        reg.register(name, description=name, depends_on=deps)(_Agent)

    for name in ("a", "b", "c"):
        make(name)
    make("final", ("a", "b", "c"))
    return reg


def _orchestrator(session_factory, reg: AgentRegistry, **limits) -> PipelineOrchestrator:
    ctx = make_context()
    return PipelineOrchestrator(
        AgentRunner(session_factory, NullKnowledgeStore()),
        reg,
        build_agent=lambda name: reg.get(name).agent_cls(ctx),
        **limits,
    )


@pytest.mark.unit
async def test_dependents_run_after_dependencies(concurrent_session_factory) -> None:
    tracker = _Tracker()
    report = await _orchestrator(concurrent_session_factory, _registry(tracker)).run(
        ["AAPL"], run_date=RUN_DATE
    )

    order = [name for kind, name, _ in tracker.events if kind == "start"]
    assert order[-1] == "final"
    assert set(order[:3]) == {"a", "b", "c"}
    assert report.counts == {"completed": 4}
    assert report.run_date == RUN_DATE


@pytest.mark.unit
async def test_concurrency_is_bounded(concurrent_session_factory) -> None:
    tracker = _Tracker()
    orchestrator = _orchestrator(
        concurrent_session_factory,
        _registry(tracker),
        max_concurrent_symbols=3,
        max_concurrent_agents=2,
    )
    await orchestrator.run(["AAPL", "MSFT", "NVDA"], run_date=RUN_DATE)
    assert tracker.peak == 2


@pytest.mark.unit
async def test_failures_are_reported_and_pipeline_continues(concurrent_session_factory) -> None:
    tracker = _Tracker()
    report = await _orchestrator(concurrent_session_factory, _registry(tracker, failing={"b"})).run(
        ["AAPL"], run_date=RUN_DATE
    )
    assert [o.agent for o in report.failed] == ["b"]
    assert report.counts == {"completed": 3, "failed": 1}  # final still ran with what it had
    async with concurrent_session_factory() as session:
        runs = (await session.execute(select(AgentRun))).scalars().all()
    assert {r.pipeline_run_id for r in runs} == {report.pipeline_run_id}


@pytest.mark.unit
async def test_rerun_skips_and_force_reruns(concurrent_session_factory) -> None:
    tracker = _Tracker()
    orchestrator = _orchestrator(concurrent_session_factory, _registry(tracker))
    await orchestrator.run(["AAPL"], run_date=RUN_DATE)
    assert (await orchestrator.run(["AAPL"], run_date=RUN_DATE)).counts == {"skipped": 4}
    forced = await orchestrator.run(["AAPL"], agents=["a"], force=True, run_date=RUN_DATE)
    assert forced.counts == {"completed": 1}


@pytest.mark.unit
async def test_input_validation_happens_before_running(concurrent_session_factory) -> None:
    tracker = _Tracker()
    orchestrator = _orchestrator(concurrent_session_factory, _registry(tracker))
    with pytest.raises(ValueError):
        await orchestrator.run(["AAPL", "bad;symbol"])
    with pytest.raises(KeyError):
        await orchestrator.run(["AAPL"], agents=["nope"])
    assert tracker.events == []

    report = await orchestrator.run(["aapl", "AAPL"], agents=["a"], run_date=RUN_DATE)
    assert len(report.outcomes) == 1  # duplicates collapsed after normalisation


@pytest.mark.unit
async def test_pipeline_logs_carry_its_id_and_report_llm_totals(
    concurrent_session_factory, caplog
) -> None:
    import logging

    from app.core.logging import ContextFilter

    caplog.handler.addFilter(ContextFilter())
    caplog.set_level(logging.INFO)
    report = await _orchestrator(concurrent_session_factory, _registry(_Tracker())).run(
        ["AAPL"], run_date=RUN_DATE
    )
    runner_lines = [r for r in caplog.records if r.name == "app.agents.runner"]
    assert runner_lines and {r.pipeline_run_id for r in runner_lines} == {report.pipeline_run_id}
    (finished,) = (r for r in caplog.records if r.message == "Pipeline finished")
    assert finished.llm_calls == 0 and finished.cost_usd == 0
    assert report.usage == {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0,
        "llm_fallbacks": 0,
    }
