"""
Scheduler — every job that runs on its own, in one table (JOBS):

  daily_pipeline       PIPELINE_SCHEDULE     full pipeline for the watchlist
  nightly_maintenance  MAINTENANCE_SCHEDULE  prune llm_calls to LLM_CALL_RETENTION_DAYS

Nothing is scheduled unless SCHEDULER_ENABLED=true; a job whose schedule is
empty stays off. Schedules are crontab lines in New York time. The watchlist is
read from the database when the job fires, so changes apply to the next run
without a restart. Runs are idempotent, so a repeated or late job is safe.
`python -m scripts.schedules` shows what is configured and when it next runs.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import MARKET_TZ, utcnow
from app.core.config import Settings
from app.pipeline.orchestrator import PipelineOrchestrator
from app.repositories.llm_calls import LLMCallRepository
from app.repositories.watchlist import WatchlistRepository

logger = logging.getLogger(__name__)

DAILY_JOB_ID = "daily_pipeline"
MAINTENANCE_JOB_ID = "nightly_maintenance"


SymbolsProvider = Callable[[], Awaitable[list[str]]]


async def load_watchlist(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    """The watchlist as stored now (the scheduler's symbols provider)."""
    async with session_factory() as session:
        return await WatchlistRepository(session).symbols()


async def run_daily_pipeline(
    orchestrator: PipelineOrchestrator, symbols_provider: SymbolsProvider
) -> None:
    symbols = await symbols_provider()
    if not symbols:
        logger.warning("Daily pipeline skipped: the watchlist is empty")
        return
    report = await orchestrator.run(symbols)
    if report.failed:
        logger.warning(
            "Daily pipeline finished with failures",
            extra={"pipeline_run_id": report.pipeline_run_id, "counts": report.counts},
        )


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
            "Full pipeline (all agents) for the watchlist",
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
    )


def create_scheduler(
    orchestrator: PipelineOrchestrator,
    symbols_provider: SymbolsProvider,
    maintenance: Callable[[], Awaitable[object]] | None = None,
    *,
    pipeline_schedule: str = "30 18 * * mon-fri",
    maintenance_schedule: str = "15 3 * * *",
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MARKET_TZ)
    if pipeline_schedule.strip():
        scheduler.add_job(
            run_daily_pipeline,
            trigger=CronTrigger.from_crontab(pipeline_schedule, timezone=MARKET_TZ),
            args=[orchestrator, symbols_provider],
            id=DAILY_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    if maintenance is not None and maintenance_schedule.strip():
        scheduler.add_job(
            maintenance,
            trigger=CronTrigger.from_crontab(maintenance_schedule, timezone=MARKET_TZ),
            id=MAINTENANCE_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    for job in scheduler.get_jobs():
        logger.info("Scheduled job registered", extra={"job": job.id, "trigger": str(job.trigger)})
    return scheduler
