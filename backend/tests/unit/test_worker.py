import asyncio
import logging

import pytest

from app.core.config import Settings
from app.worker import run_worker


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [True, False])
async def test_worker_runs_until_stopped(session_factory, caplog, enabled: bool) -> None:
    caplog.set_level(logging.INFO, logger="app.worker")
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(
            Settings(openviking_enabled=False, scheduler_enabled=enabled), session_factory, stop
        )
    )
    await asyncio.sleep(0.05)
    started = next(r for r in caplog.records if r.message == "Scheduler worker started")
    assert started.scheduling is enabled  # disabled: it idles, scheduling nothing
    assert not task.done()

    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert "Scheduler worker stopped" in caplog.text
