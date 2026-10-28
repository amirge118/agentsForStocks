"""
Scheduler worker — runs the daily pipeline scheduler in its own process.

Production layout: N API processes with RUN_SCHEDULER=false, plus exactly ONE
`python -m app.worker`. With SCHEDULER_ENABLED=false (the default) the worker
starts, schedules nothing and idles until stopped. Agent runs are idempotent,
so an accidental second worker wastes API calls but never corrupts or
duplicates results.
"""

import asyncio
import logging
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.scheduler import build_scheduler
from app.container import build_container
from app.core.config import Settings

logger = logging.getLogger(__name__)


async def run_worker(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
) -> None:
    """Start the scheduler and keep it running until `stop` is set."""
    container = build_container(settings, session_factory)
    scheduler = build_scheduler(
        settings,
        container.orchestrator,
        session_factory,
        settler=container.settler,
        lock=container.lock,
        registry=container.registry,
    )
    if scheduler is not None:
        scheduler.start()
    logger.info("Scheduler worker started", extra={"scheduling": scheduler is not None})
    try:
        await stop.wait()
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await container.aclose()
        logger.info("Scheduler worker stopped")


async def _main() -> None:
    from app.core.config import settings
    from app.db.session import AsyncSessionLocal

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await run_worker(settings, AsyncSessionLocal, stop)


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    from app.core.config import settings as _settings
    from app.core.logging import configure_logging
    from app.db.session import engine
    from app.observability.telemetry import configure_telemetry

    configure_logging(_settings.log_format, _settings.log_level)
    telemetry = configure_telemetry(_settings, service_name="agentsforstocks-worker", engine=engine)
    try:
        asyncio.run(_main())
    finally:
        telemetry.shutdown()
