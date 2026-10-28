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
    for _ in range(100):  # startup writes to the DB: wait for it, not a fixed time
        started = [r for r in caplog.records if r.message == "Scheduler worker started"]
        if started:
            break
        await asyncio.sleep(0.02)
    assert started[0].scheduling is enabled  # disabled: it idles, scheduling nothing
    assert not task.done()
    # A running scheduler is noted, so /health can tell a fresh install from a miss
    from app.pipeline.job_runs import SCHEDULER_STARTED
    from app.repositories.job_runs import JobRunRepository

    async with session_factory() as session:
        noted = await JobRunRepository(session).first(SCHEDULER_STARTED)
    assert (noted is not None) is enabled

    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert "Scheduler worker stopped" in caplog.text
