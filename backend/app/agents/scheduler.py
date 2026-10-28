"""
Scheduler — every job that runs on its own, in one table (JOBS):

  daily_pipeline       PIPELINE_SCHEDULE     settle past decisions, then the full
                                             pipeline for the watchlist
  nightly_maintenance  MAINTENANCE_SCHEDULE  prune llm_calls to LLM_CALL_RETENTION_DAYS

Nothing is scheduled unless SCHEDULER_ENABLED=true; a job whose schedule is
empty stays off. Schedules are crontab lines in New York time. The watchlist is
read from the database when the job fires, so changes apply to the next run
without a restart. Runs are idempotent, so a repeated or late job is safe.
`python -m scripts.schedules` shows what is configured and when it next runs.

Before the agents, the daily job settles past decisions against realised prices
(app/pipeline/settlement.py) when a settler is given — also with an empty
watchlist, since it scores what was already decided. A settlement failure is
logged and never stops the pipeline.

Reliability: every job run is recorded in job_runs (app/pipeline/job_runs.py),
so /health reports a daily run that was missed or failed; the daily run holds
the PipelineLock (one run at a time, across processes); and agent runs that
failed are retried later the same day (app/pipeline/retry.py).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.registry import AgentRegistry
from app.core.clock import MARKET_TZ, utcnow
from app.core.config import Settings
from app.pipeline.job_runs import JobRecorder, JobState, job_state
from app.pipeline.lock import PipelineLock
from app.pipeline.orchestrator import PipelineOrchestrator, PipelineReport
from app.pipeline.retry import FailedRunRetry
from app.pipeline.settlement import OutcomeSettler
from app.repositories.llm_calls import LLMCallRepository
from app.repositories.watchlist import WatchlistRepository

logger = logging.getLogger(__name__)

DAILY_JOB_ID = "daily_pipeline"
MAINTENANCE_JOB_ID = "nightly_maintenance"


SymbolsProvider = Callable[[], Awaitable[list[str]]]
# The daily run waits this long for a manual run to finish, then fails (recorded)
LOCK_WAIT_SECONDS = 2 * 3600.0


async def load_watchlist(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    """The watchlist as stored now (the scheduler's symbols provider)."""
    async with session_factory() as session:
        return await WatchlistRepository(session).symbols()


async def run_daily_pipeline(
    orchestrator: PipelineOrchestrator,
    symbols_provider: SymbolsProvider,
    settler: OutcomeSettler | None = None,
    *,
    lock: PipelineLock | None = None,
    retry: FailedRunRetry | None = None,
) -> PipelineReport | None:
    held = await lock.acquire(LOCK_WAIT_SECONDS) if lock is not None else None
    if lock is not None and held is None:
        raise RuntimeError("another pipeline run held the lock too long; daily run not started")
    try:
        if settler is not None:
            try:
                await settler.settle()
            except Exception:
                logger.exception("Outcome settlement failed; the pipeline runs anyway")
        symbols = await symbols_provider()
        if not symbols:
            logger.warning("Daily pipeline skipped: the watchlist is empty")
            return None
        report = await orchestrator.run(symbols)
    finally:
        if held is not None:
            await held.release()
    if report.failed:
        logger.warning(
            "Daily pipeline finished with failures",
            extra={"pipeline_run_id": report.pipeline_run_id, "counts": report.counts},
        )
        if retry is not None:
            retry.plan(report)
    return report


async def prune_llm_calls(
    session_factory: async_sessionmaker[AsyncSession], retention_days: int
) -> int:
    """Delete llm_calls rows older than the retention window. Returns the number deleted."""
    cutoff = utcnow() - timedelta(days=retention_days)
    async with session_factory() as session:
        deleted = await LLMCallRepository(session).delete_older_than(cutoff)
        await session.commit()
    logger.info(
        "Pruned LLM call ledger", extra={"deleted": deleted, "retention_days": retention_days}
    )
    return deleted


@dataclass(frozen=True)
class JobSetting:
    job_id: str
    setting: str  # the env var that holds its schedule
    description: str
    schedule: str  # crontab, New York time; "" = off

    @property
    def enabled(self) -> bool:
        return bool(self.schedule.strip())

    def next_run(self, now: datetime | None = None) -> datetime | None:
        if not self.enabled:
            return None
        trigger = CronTrigger.from_crontab(self.schedule, timezone=MARKET_TZ)
        return trigger.get_next_fire_time(None, now or utcnow())


def jobs(settings: Settings) -> list[JobSetting]:
    """Every scheduled job and its configured timing (whether or not the scheduler is on)."""
    return [
        JobSetting(
            DAILY_JOB_ID,
            "PIPELINE_SCHEDULE",
            "Settle past decisions, then the full pipeline for the watchlist",
            settings.pipeline_schedule,
        ),
        JobSetting(
            MAINTENANCE_JOB_ID,
            "MAINTENANCE_SCHEDULE",
            f"Prune llm_calls older than {settings.llm_call_retention_days} days",
            settings.maintenance_schedule,
        ),
    ]


def build_scheduler(
    settings: Settings,
    orchestrator: PipelineOrchestrator,
    session_factory: async_sessionmaker[AsyncSession],
    settler: OutcomeSettler | None = None,
    *,
    lock: PipelineLock | None = None,
    registry: AgentRegistry | None = None,
) -> AsyncIOScheduler | None:
    """The configured scheduler, or None when SCHEDULER_ENABLED is off (nothing runs)."""
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false): no job runs on its own")
        return None
    return create_scheduler(
        orchestrator,
        partial(load_watchlist, session_factory),
        maintenance=partial(prune_llm_calls, session_factory, settings.llm_call_retention_days),
        pipeline_schedule=settings.pipeline_schedule,
        maintenance_schedule=settings.maintenance_schedule,
        settler=settler,
        lock=lock,
        registry=registry,
        recorder=JobRecorder(session_factory),
        retry_delay=timedelta(minutes=settings.pipeline_retry_delay_minutes),
        retry_attempts=settings.pipeline_retry_attempts,
    )


def create_scheduler(
    orchestrator: PipelineOrchestrator,
    symbols_provider: SymbolsProvider,
    maintenance: Callable[[], Awaitable[object]] | None = None,
    *,
    pipeline_schedule: str = "30 18 * * mon-fri",
    maintenance_schedule: str = "15 3 * * *",
    settler: OutcomeSettler | None = None,
    lock: PipelineLock | None = None,
    registry: AgentRegistry | None = None,
    recorder: JobRecorder | None = None,
    retry_delay: timedelta = timedelta(minutes=30),
    retry_attempts: int = 2,
) -> AsyncIOScheduler:
    """
    The jobs, each run through `recorder` (job_runs) when one is given. Failed agent
    runs are retried when a registry is given and `retry_attempts` > 0.
    """
    scheduler = AsyncIOScheduler(timezone=MARKET_TZ)
    retry = None
    if registry is not None and retry_attempts > 0:
        retry = FailedRunRetry(
            orchestrator,
            registry,
            scheduler.add_job,
            delay=retry_delay,
            attempts=retry_attempts,
            lock=lock,
            run_job=recorder.run if recorder is not None else None,
        )

    def recorded(job_id: str, func: Callable[..., Awaitable[object]], args: list) -> tuple:
        if recorder is None:
            return func, args
        return recorder.run, [job_id, func, *args]

    if pipeline_schedule.strip():
        func, args = recorded(DAILY_JOB_ID, run_daily_pipeline, [orchestrator, symbols_provider])
        scheduler.add_job(
            func,
            trigger=CronTrigger.from_crontab(pipeline_schedule, timezone=MARKET_TZ),
            args=args,
            kwargs={"settler": settler, "lock": lock, "retry": retry},
            id=DAILY_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    if maintenance is not None and maintenance_schedule.strip():
        func, args = recorded(MAINTENANCE_JOB_ID, maintenance, [])
        scheduler.add_job(
            func,
            trigger=CronTrigger.from_crontab(maintenance_schedule, timezone=MARKET_TZ),
            args=args,
            id=MAINTENANCE_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    for job in scheduler.get_jobs():
        logger.info("Scheduled job registered", extra={"job": job.id, "trigger": str(job.trigger)})
    return scheduler


async def job_health(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
) -> dict[str, JobState]:
    """Each enabled job's latest due run: ok, running, partial, failed, missed or not due."""
    states: dict[str, JobState] = {}
    for job in jobs(settings):
        if job.enabled:
            states[job.job_id] = await job_state(
                session_factory, job.job_id, job.schedule, now or utcnow()
            )
    return states
