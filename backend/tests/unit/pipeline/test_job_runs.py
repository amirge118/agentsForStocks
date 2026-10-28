import json
from datetime import UTC, datetime

import pytest

from app.agents.runner import RunOutcome
from app.pipeline.job_runs import JobRecorder, job_state, last_due
from app.pipeline.orchestrator import PipelineReport
from app.repositories.job_runs import JobRunRepository

DAILY = "30 18 * * mon-fri"
# Tuesday 2026-10-27 21:00 New York: the 18:30 run is due (18:30 + 2h grace)
NOW = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)


async def _latest(session_factory, job_id: str):
    async with session_factory() as session:
        return await JobRunRepository(session).latest(job_id)


@pytest.mark.unit
async def test_a_job_run_is_recorded_with_how_it_ended(session_factory) -> None:
    recorder = JobRecorder(session_factory)
    failed = RunOutcome("moat", "AAPL", "r", "failed", error="x")
    report = PipelineReport("p1", None, (failed,))

    async def daily() -> PipelineReport:
        return report

    assert await recorder.run("daily_pipeline", daily) is report
    run = await _latest(session_factory, "daily_pipeline")
    assert run.status == "partial" and run.finished_at is not None
    assert json.loads(run.detail) == {"pipeline_run_id": "p1", "failed": 1}

    async def prune(days: int) -> int:
        return days

    assert await recorder.run("nightly_maintenance", prune, 3) == 3
    assert (await _latest(session_factory, "nightly_maintenance")).detail == "3"


@pytest.mark.unit
async def test_a_failed_job_is_recorded_and_still_raises(session_factory) -> None:
    async def boom() -> None:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await JobRecorder(session_factory).run("daily_pipeline", boom)
    run = await _latest(session_factory, "daily_pipeline")
    assert (run.status, run.detail) == ("failed", "RuntimeError: provider down")


@pytest.mark.unit
async def test_the_job_runs_even_when_it_cannot_be_recorded(caplog) -> None:
    def broken():
        raise RuntimeError("db down")

    async def job() -> str:
        return "done"

    assert await JobRecorder(broken).run("daily_pipeline", job) == "done"
    assert "Could not record the job start" in caplog.text


@pytest.mark.unit
def test_last_due_is_the_latest_scheduled_time_in_new_york() -> None:
    assert last_due(DAILY, NOW).isoformat() == "2026-10-27T18:30:00-04:00"
    # Monday morning: the last weekday run was Friday's
    monday = datetime(2026, 10, 26, 13, tzinfo=UTC)
    assert last_due(DAILY, monday).isoformat() == "2026-10-23T18:30:00-04:00"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "expected"),
    [("running", "running"), ("failed", "failed"), ("partial", "partial"), ("completed", "ok")],
)
async def test_job_state_reads_the_due_runs_record(session_factory, status, expected) -> None:
    from app.models.job_run import JobRun

    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "missed"
    async with session_factory() as session:
        session.add(
            JobRun(
                id="r",
                job_id="daily_pipeline",
                started_at=datetime(2026, 10, 27, 22, 30, 5, tzinfo=UTC),  # 18:30 New York
                status=status,
            )
        )
        await session.commit()
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == expected


@pytest.mark.unit
async def test_a_job_is_not_judged_before_its_first_due_run(session_factory) -> None:
    # Christmas only, never within the last eight days
    assert await job_state(session_factory, "x", "0 9 25 12 *", NOW) == "not due"


@pytest.mark.unit
async def test_a_run_before_the_due_time_does_not_count(session_factory) -> None:
    from app.models.job_run import JobRun

    async with session_factory() as session:
        session.add(
            JobRun(
                id="old",
                job_id="daily_pipeline",
                started_at=datetime(2026, 10, 26, 22, 30, tzinfo=UTC),  # Monday's run
                status="completed",
            )
        )
        await session.commit()
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "missed"
    async with session_factory() as session:
        session.add(
            JobRun(
                id="today",
                job_id="daily_pipeline",
                started_at=datetime(2026, 10, 27, 22, 30, 5, tzinfo=UTC),
                status="completed",
            )
        )
        await session.commit()
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "ok"


@pytest.mark.unit
async def test_a_run_due_before_the_first_scheduler_start_is_not_missed(session_factory) -> None:
    from app.models.job_run import JobRun
    from app.pipeline.job_runs import SCHEDULER_STARTED

    # A worker that never started: today's run is missed
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "missed"

    async def started(at: datetime, run_id: str) -> None:
        async with session_factory() as session:
            session.add(
                JobRun(id=run_id, job_id=SCHEDULER_STARTED, started_at=at, status="completed")
            )
            await session.commit()

    # Installed after today's 18:30 (22:30 UTC): nothing was missed yet
    await started(datetime(2026, 10, 27, 23, 0, tzinfo=UTC), "fresh")
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "not due"


@pytest.mark.unit
async def test_a_later_restart_does_not_hide_a_miss(session_factory) -> None:
    from app.models.job_run import JobRun
    from app.pipeline.job_runs import SCHEDULER_STARTED

    async with session_factory() as session:
        for run_id, at in (("first", datetime(2026, 10, 20, tzinfo=UTC)), ("restart", NOW)):
            session.add(
                JobRun(id=run_id, job_id=SCHEDULER_STARTED, started_at=at, status="completed")
            )
        await session.commit()
    assert await job_state(session_factory, "daily_pipeline", DAILY, NOW) == "missed"


@pytest.mark.unit
async def test_recorder_notes_a_scheduler_start(session_factory) -> None:
    from app.pipeline.job_runs import SCHEDULER_STARTED

    await JobRecorder(session_factory).scheduler_started()
    run = await _latest(session_factory, SCHEDULER_STARTED)
    assert run is not None and run.status == "completed"
