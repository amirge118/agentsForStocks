from unittest.mock import AsyncMock

import pytest

from app.agents.runner import RunOutcome
from app.agents.scheduler import (
    DAILY_JOB_ID,
    MAINTENANCE_JOB_ID,
    build_scheduler,
    create_scheduler,
    jobs,
    load_watchlist,
    run_daily_pipeline,
)
from app.core.config import Settings
from app.pipeline.orchestrator import PipelineReport


@pytest.mark.unit
def test_daily_job_runs_weekdays_after_close() -> None:
    orchestrator = AsyncMock()
    provider = AsyncMock(return_value=["AAPL"])
    scheduler = create_scheduler(orchestrator, provider)
    job = scheduler.get_job(DAILY_JOB_ID)
    assert str(job.trigger) == (
        "cron[month='*', day='*', day_of_week='mon-fri', hour='18', minute='30']"
    )
    assert job.args == (orchestrator, provider)
    assert str(scheduler.timezone) == "America/New_York"


@pytest.mark.unit
async def test_run_daily_pipeline_runs_watchlist(caplog) -> None:
    failed = RunOutcome("moat", "AAPL", "r1", "failed", error="x")
    orchestrator = AsyncMock()
    orchestrator.run.return_value = PipelineReport("p1", run_date=None, outcomes=(failed,))

    await run_daily_pipeline(orchestrator, AsyncMock(return_value=["AAPL"]))

    orchestrator.run.assert_awaited_once_with(["AAPL"])
    assert "finished with failures" in caplog.text


@pytest.mark.unit
async def test_run_daily_pipeline_skips_an_empty_watchlist(caplog) -> None:
    orchestrator = AsyncMock()

    await run_daily_pipeline(orchestrator, AsyncMock(return_value=[]))

    orchestrator.run.assert_not_awaited()
    assert "watchlist is empty" in caplog.text


@pytest.mark.unit
async def test_load_watchlist_reads_the_current_list(session_factory) -> None:
    from app.repositories.watchlist import WatchlistRepository

    assert await load_watchlist(session_factory) == []
    async with session_factory() as session:
        await WatchlistRepository(session).add("MSFT")
        await WatchlistRepository(session).add("AAPL")
        await session.commit()
    # Read when the job fires, so a symbol added after startup is picked up
    assert await load_watchlist(session_factory) == ["MSFT", "AAPL"]


@pytest.mark.unit
def test_maintenance_job_is_registered_when_given() -> None:
    from app.agents.scheduler import MAINTENANCE_JOB_ID

    assert create_scheduler(AsyncMock(), AsyncMock()).get_job(MAINTENANCE_JOB_ID) is None
    maintenance = AsyncMock()
    job = create_scheduler(AsyncMock(), AsyncMock(), maintenance=maintenance).get_job(
        MAINTENANCE_JOB_ID
    )
    assert str(job.trigger) == "cron[month='*', day='*', day_of_week='*', hour='3', minute='15']"
    assert job.func is maintenance


@pytest.mark.unit
async def test_prune_llm_calls_deletes_rows_past_retention(session_factory, caplog) -> None:
    import logging
    from datetime import timedelta

    from app.agents.scheduler import prune_llm_calls
    from app.core.clock import utcnow
    from app.models.llm_call import LLMCall

    def _call(call_id: str, age_days: int) -> LLMCall:
        return LLMCall(
            call_id=call_id,
            created_at=utcnow() - timedelta(days=age_days),
            model="m",
            prompt_version="v",
            status="ok",
            latency_ms=1,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )

    async with session_factory() as session:
        session.add_all([_call("keep", 10), _call("drop", 120)])
        await session.commit()
    caplog.set_level(logging.INFO, logger="app.agents.scheduler")
    assert await prune_llm_calls(session_factory, retention_days=90) == 1
    assert "Pruned LLM call ledger" in caplog.text


@pytest.mark.unit
def test_nothing_is_scheduled_unless_enabled(session_factory) -> None:
    assert Settings().scheduler_enabled is False
    assert build_scheduler(Settings(), AsyncMock(), session_factory) is None

    settings = Settings(scheduler_enabled=True, pipeline_schedule="0 7 * * 1")
    scheduler = build_scheduler(settings, AsyncMock(), session_factory)
    assert scheduler is not None
    assert {j.id for j in scheduler.get_jobs()} == {DAILY_JOB_ID, MAINTENANCE_JOB_ID}
    assert "day_of_week='1', hour='7', minute='0'" in str(scheduler.get_job(DAILY_JOB_ID).trigger)


@pytest.mark.unit
def test_an_empty_schedule_turns_one_job_off(session_factory) -> None:
    settings = Settings(scheduler_enabled=True, maintenance_schedule="")
    scheduler = build_scheduler(settings, AsyncMock(), session_factory)
    assert [j.id for j in scheduler.get_jobs()] == [DAILY_JOB_ID]
    assert [(j.job_id, j.enabled) for j in jobs(settings)] == [
        (DAILY_JOB_ID, True),
        (MAINTENANCE_JOB_ID, False),
    ]


@pytest.mark.unit
def test_next_run_is_in_new_york_time() -> None:
    from datetime import UTC, datetime

    daily, maintenance = jobs(Settings())
    # Monday 2026-10-26 12:00 UTC = 08:00 New York → today's 18:30 run
    now = datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert daily.next_run(now).isoformat() == "2026-10-26T18:30:00-04:00"
    # Friday evening → the following Monday
    assert daily.next_run(datetime(2026, 10, 30, 23, tzinfo=UTC)).day == 2
    assert maintenance.next_run(now).isoformat() == "2026-10-27T03:15:00-04:00"
    assert jobs(Settings(pipeline_schedule=" "))[0].next_run(now) is None


@pytest.mark.unit
def test_a_bad_schedule_fails_at_startup(session_factory) -> None:
    settings = Settings(scheduler_enabled=True, pipeline_schedule="every day")
    with pytest.raises(ValueError):
        build_scheduler(settings, AsyncMock(), session_factory)
