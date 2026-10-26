"""
Scheduler — one daily job (weekdays 18:30 New York time, after the close) that
runs the full pipeline for the watchlist. Ordering and concurrency are the
orchestrator's job; runs are idempotent, so a repeated or late job is safe.

Before the agents, the daily job settles past decisions against realised prices
(app/pipeline/settlement.py) when a settler is given; a settlement failure is
logged and never stops the pipeline.

Optionally a nightly maintenance job (03:15 New York) — e.g. pruning the
llm_calls ledger to its retention window.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import MARKET_TZ, utcnow
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.settlement import OutcomeSettler
from app.repositories.llm_calls import LLMCallRepository

logger = logging.getLogger(__name__)

DAILY_JOB_ID = "daily_pipeline"
MAINTENANCE_JOB_ID = "nightly_maintenance"


async def run_daily_pipeline(
    orchestrator: PipelineOrchestrator,
    symbols: list[str],
    settler: OutcomeSettler | None = None,
) -> None:
    if settler is not None:
        try:
            await settler.settle()
        except Exception:
            logger.exception("Outcome settlement failed; the pipeline runs anyway")
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


def create_scheduler(
    orchestrator: PipelineOrchestrator,
    symbols: list[str],
    maintenance: Callable[[], Awaitable[object]] | None = None,
    settler: OutcomeSettler | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MARKET_TZ)
    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30),
        args=[orchestrator, symbols],
        kwargs={"settler": settler},
        id=DAILY_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    if maintenance is not None:
        scheduler.add_job(
            maintenance,
            trigger=CronTrigger(hour=3, minute=15),
            id=MAINTENANCE_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    logger.info("Registered daily pipeline for %s", symbols)
    return scheduler
