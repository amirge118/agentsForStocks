"""
Agent scheduler — one daily job (weekdays 18:30 New York time, after market close)
runs every registered agent for every watchlist symbol, in dependency order.

Agent order comes from the registry, so adding an agent never touches this file.
All runs are idempotent, so a misfired or repeated job is safe.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.container import Container
from app.core.clock import MARKET_TZ, market_today

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=MARKET_TZ)


async def run_symbol(container: Container, symbol: str) -> None:
    run_date = market_today()
    for level in container.registry.execution_levels():
        await asyncio.gather(
            *(container.runner.run(container.build_agent(name), symbol, run_date) for name in level)
        )


async def run_watchlist(container: Container) -> None:
    for symbol in container.settings.watchlist_symbols:
        await run_symbol(container, symbol)


def register_jobs(container: Container) -> None:
    scheduler.add_job(
        run_watchlist,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30),
        args=[container],
        id="daily_pipeline",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Registered daily pipeline for %s", container.settings.watchlist_symbols)
