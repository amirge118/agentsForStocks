from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.registry import AgentRegistry
from app.agents.runner import RunOutcome
from app.agents.scheduler import run_daily_pipeline
from app.pipeline.lock import PipelineLock
from app.pipeline.orchestrator import PipelineReport
from app.pipeline.retry import RETRY_JOB_ID, FailedRunRetry

DAY = date(2026, 10, 27)


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    for name, deps in (
        ("technicals", ()),
        ("moat", ()),
        ("risk", ()),
        ("recommendation", ("moat", "risk")),
        ("outcome_review", ()),
    ):
        reg.register(name, description=name, depends_on=deps)(type(name, (), {}))
    return reg


def _report(*failed: tuple[str, str], ok: tuple[str, str] | None = None) -> PipelineReport:
    outcomes = [RunOutcome(a, s, "r", "failed", error="provider down") for a, s in failed]
    if ok:
        outcomes.append(RunOutcome(ok[0], ok[1], "r", "completed"))
    return PipelineReport("p1", DAY, tuple(outcomes))


@pytest.mark.unit
def test_downstream_includes_every_dependent() -> None:
    reg = _registry()
    assert reg.downstream(["moat"]) == {"moat", "recommendation"}
    assert reg.downstream(["technicals"]) == {"technicals"}


@pytest.mark.unit
def test_failed_runs_are_scheduled_for_later_and_recorded() -> None:
    add_job = MagicMock()
    run_job = AsyncMock()
    retry = FailedRunRetry(
        AsyncMock(), _registry(), add_job, delay=timedelta(minutes=30), run_job=run_job
    )
    assert retry.plan(_report(ok=("moat", "AAPL"))) is False  # nothing failed
    add_job.assert_not_called()

    assert retry.plan(_report(("moat", "AAPL"), ("moat", "AAPL"), ("risk", "MSFT"))) is True
    kwargs = add_job.call_args.kwargs
    assert kwargs["trigger"] == "date" and kwargs["id"] == f"{RETRY_JOB_ID}_1"
    assert kwargs["args"] == [
        RETRY_JOB_ID,
        retry.retry,
        DAY,
        [("moat", "AAPL"), ("risk", "MSFT")],
        1,
    ]
    assert add_job.call_args.args == (run_job,)


@pytest.mark.unit
async def test_a_retry_reruns_the_failed_agents_and_what_depends_on_them(session_factory) -> None:
    orchestrator = AsyncMock()
    orchestrator.run.side_effect = lambda symbols, **kw: PipelineReport(
        "r", DAY, tuple(RunOutcome(a, symbols[0], "r", "completed") for a in kw["agents"])
    )
    add_job = MagicMock()
    retry = FailedRunRetry(orchestrator, _registry(), add_job, lock=PipelineLock(session_factory))

    report = await retry.retry(DAY, [("moat", "AAPL"), ("technicals", "MSFT")], 1)

    calls = [(c.args[0], c.kwargs) for c in orchestrator.run.await_args_list]
    assert calls == [
        (["AAPL"], {"agents": ["moat", "recommendation"], "force": True, "run_date": DAY}),
        (["MSFT"], {"agents": ["technicals"], "force": True, "run_date": DAY}),
    ]
    assert report.counts == {"completed": 3}
    add_job.assert_not_called()  # all fixed: no further round


@pytest.mark.unit
async def test_retries_stop_after_the_last_attempt(caplog) -> None:
    still_down = _report(("moat", "AAPL"))
    orchestrator = AsyncMock()
    orchestrator.run.return_value = still_down
    add_job = MagicMock()
    retry = FailedRunRetry(orchestrator, _registry(), add_job, attempts=2)

    await retry.retry(DAY, [("moat", "AAPL")], 1)
    assert add_job.call_args.kwargs["id"] == f"{RETRY_JOB_ID}_2"
    add_job.reset_mock()
    await retry.retry(DAY, [("moat", "AAPL")], 2)
    add_job.assert_not_called()
    assert "still failing after every retry" in caplog.text


@pytest.mark.unit
async def test_the_daily_run_plans_a_retry_and_releases_the_lock(session_factory) -> None:
    orchestrator = AsyncMock()
    orchestrator.run.return_value = _report(("moat", "AAPL"))
    retry = MagicMock()
    lock = PipelineLock(session_factory)

    report = await run_daily_pipeline(
        orchestrator, AsyncMock(return_value=["AAPL"]), lock=lock, retry=retry
    )

    retry.plan.assert_called_once_with(report)
    held = await lock.acquire()
    assert held is not None  # given back after the run
    await held.release()


@pytest.mark.unit
async def test_the_daily_run_fails_when_the_lock_stays_busy(session_factory, monkeypatch) -> None:
    from app.agents import scheduler

    monkeypatch.setattr(scheduler, "LOCK_WAIT_SECONDS", 0.01)
    lock = PipelineLock(session_factory)
    manual = await lock.acquire()
    orchestrator = AsyncMock()
    with pytest.raises(RuntimeError, match="lock"):
        await run_daily_pipeline(orchestrator, AsyncMock(return_value=["AAPL"]), lock=lock)
    orchestrator.run.assert_not_awaited()
    await manual.release()


@pytest.mark.unit
async def test_the_lock_is_released_when_the_run_crashes(session_factory) -> None:
    orchestrator = AsyncMock()
    orchestrator.run.side_effect = RuntimeError("boom")
    lock = PipelineLock(session_factory)
    with pytest.raises(RuntimeError):
        await run_daily_pipeline(orchestrator, AsyncMock(return_value=["AAPL"]), lock=lock)
    held = await lock.acquire()
    assert held is not None
    await held.release()
