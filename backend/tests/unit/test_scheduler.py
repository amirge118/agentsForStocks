from unittest.mock import AsyncMock

import pytest

from app.agents.runner import RunOutcome
from app.agents.scheduler import DAILY_JOB_ID, create_scheduler, run_daily_pipeline
from app.pipeline.orchestrator import PipelineReport


@pytest.mark.unit
def test_daily_job_runs_weekdays_after_close() -> None:
    orchestrator = AsyncMock()
    scheduler = create_scheduler(orchestrator, ["AAPL"])
    job = scheduler.get_job(DAILY_JOB_ID)
    assert str(job.trigger) == "cron[day_of_week='mon-fri', hour='18', minute='30']"
    assert job.args == (orchestrator, ["AAPL"])
    assert str(scheduler.timezone) == "America/New_York"


@pytest.mark.unit
async def test_run_daily_pipeline_runs_watchlist(caplog) -> None:
    failed = RunOutcome("moat", "AAPL", "r1", "failed", error="x")
    orchestrator = AsyncMock()
    orchestrator.run.return_value = PipelineReport("p1", run_date=None, outcomes=(failed,))

    await run_daily_pipeline(orchestrator, ["AAPL"])

    orchestrator.run.assert_awaited_once_with(["AAPL"])
    assert "finished with failures" in caplog.text


@pytest.mark.unit
def test_maintenance_job_is_registered_when_given() -> None:
    from app.agents.scheduler import MAINTENANCE_JOB_ID

    assert create_scheduler(AsyncMock(), ["AAPL"]).get_job(MAINTENANCE_JOB_ID) is None
    maintenance = AsyncMock()
    job = create_scheduler(AsyncMock(), ["AAPL"], maintenance=maintenance).get_job(
        MAINTENANCE_JOB_ID
    )
    assert str(job.trigger) == "cron[hour='3', minute='15']"
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
