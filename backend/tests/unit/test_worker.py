import asyncio
import logging

import pytest

from app.core.config import Settings
from app.worker import run_worker


@pytest.mark.unit
async def test_worker_runs_scheduler_until_stopped(session_factory, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.worker")
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(Settings(openviking_enabled=False, watchlist="AAPL"), session_factory, stop)
    )
    await asyncio.sleep(0.05)
    assert "Scheduler worker started" in caplog.text
    assert not task.done()

    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert "Scheduler worker stopped" in caplog.text
