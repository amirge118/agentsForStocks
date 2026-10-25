"""
Scheduler — one daily job (weekdays 18:30 New York time, after the close) that
runs the full pipeline for the watchlist. Ordering and concurrency are the
orchestrator's job; runs are idempotent, so a repeated or late job is safe.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.clock import MARKET_TZ
from app.pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

DAILY_JOB_ID = "daily_pipeline"


async def run_daily_pipeline(orchestrator: PipelineOrchestrator, symbols: list[str]) -> None:
    report = await orchestrator.run(symbols)
    if report.failed:
        logger.warning(
            "Daily pipeline finished with failures",
            extra={"pipeline_run_id": report.pipeline_run_id, "counts": report.counts},
        )


def create_scheduler(orchestrator: PipelineOrchestrator, symbols: list[str]) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MARKET_TZ)
    scheduler.add_job(
        run_daily_pipeline,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30),
        args=[orchestrator, symbols],
        id=DAILY_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    logger.info("Registered daily pipeline for %s", symbols)
    return scheduler
