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
