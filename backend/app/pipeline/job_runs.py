"""
Scheduled job bookkeeping: every run of a job is recorded in job_runs (started,
finished, how it ended), and job_state() compares the record with the job's
schedule, so /health can say that today's run never happened or failed — the
worker can be up while the job is not.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import MARKET_TZ
from app.models.job_run import JobStatus
from app.observability import metrics
from app.pipeline.orchestrator import PipelineReport
from app.repositories.job_runs import JobRunRepository

logger = logging.getLogger(__name__)

# How long after its scheduled time a run may start and finish before it counts as
# missed (APScheduler still starts a job up to an hour late)
GRACE = timedelta(hours=2)
# Recorded each time a scheduler starts: a run due before the first one is not missed
# (a fresh install), while a scheduler that never started leaves every job missed
SCHEDULER_STARTED = "scheduler_started"
JobState = Literal["ok", "running", "partial", "failed", "missed", "not due"]


class JobRecorder:
    """Runs a job function and records the run. A recording failure never stops the job."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run(
        self, job_id: str, fn: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        run_id = await self._start(job_id)
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            logger.error("Scheduled job failed", extra={"job": job_id}, exc_info=True)
            await self._finish(job_id, run_id, "failed", f"{type(exc).__name__}: {exc}")
            raise
        status, detail = _outcome(result)
        await self._finish(job_id, run_id, status, detail)
        return result

    async def scheduler_started(self) -> None:
        """Note that a scheduler is running from now on (see SCHEDULER_STARTED)."""
        run_id = await self._start(SCHEDULER_STARTED)
        await self._finish(SCHEDULER_STARTED, run_id, "completed", None)

    async def _start(self, job_id: str) -> str | None:
        try:
            async with self._session_factory() as session:
                run = await JobRunRepository(session).start(job_id)
                await session.commit()
                return run.id
        except Exception as exc:
            logger.warning(
                "Could not record the job start", extra={"job": job_id, "error": str(exc)}
            )
            return None

    async def _finish(
        self, job_id: str, run_id: str | None, status: JobStatus, detail: str | None
    ) -> None:
        metrics.scheduled_jobs.add(1, {"job": job_id, "status": status})
        if run_id is None:
            return
        try:
            async with self._session_factory() as session:
                await JobRunRepository(session).finish(run_id, status, detail)
                await session.commit()
        except Exception as exc:
            logger.warning("Could not record the job end", extra={"job": job_id, "error": str(exc)})


def _outcome(result: object) -> tuple[JobStatus, str | None]:
    if isinstance(result, PipelineReport):
        detail = json.dumps({"pipeline_run_id": result.pipeline_run_id, **result.counts})
        return ("partial" if result.failed else "completed"), detail
    return "completed", None if result is None else str(result)


def last_due(schedule: str, before: datetime) -> datetime | None:
    """The job's latest scheduled time at or before `before` (looking back eight days)."""
    trigger = CronTrigger.from_crontab(schedule, timezone=MARKET_TZ)
    due, cursor = None, before - timedelta(days=8)
    while (fire := trigger.get_next_fire_time(due, cursor)) is not None and fire <= before:
        due, cursor = fire, fire + timedelta(seconds=1)
    return due


async def job_state(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    schedule: str,
    now: datetime,
) -> JobState:
    """
    How the job's latest due run went. A run is due once its scheduled time plus
    GRACE has passed; until then the one before it is judged.
    """
    due = last_due(schedule, now - GRACE)
    if due is None:
        return "not due"
    async with session_factory() as session:
        repo = JobRunRepository(session)
        run = await repo.latest(job_id, since=due - timedelta(minutes=1))
        first_start = await repo.first(SCHEDULER_STARTED)
    if run is None:
        # Due before any scheduler ever ran (a fresh install): nothing was missed yet
        if first_start is not None and due < _aware(first_start.started_at):
            return "not due"
        return "missed"
    return {"running": "running", "partial": "partial", "failed": "failed"}.get(run.status, "ok")


def _aware(at: datetime) -> datetime:
    """SQLite hands back naive datetimes; they are stored in UTC."""
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)
