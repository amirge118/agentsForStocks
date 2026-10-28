import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agents.registry import AgentRegistry
from app.pipeline.launcher import PipelineBusyError, PipelineLauncher
from app.pipeline.lock import PipelineLock


@pytest.mark.unit
async def test_one_holder_at_a_time_and_waiting_for_a_release(session_factory) -> None:
    lock = PipelineLock(session_factory)
    held = await lock.acquire()
    assert held is not None
    assert await lock.acquire() is None  # busy, and not willing to wait
    assert await lock.acquire(wait_seconds=0.01) is None  # waited, still busy

    async def release_soon() -> None:
        await asyncio.sleep(0.01)
        await held.release()

    asyncio.create_task(release_soon())
    again = await lock.acquire(wait_seconds=1)
    assert again is not None
    await again.release()
    await again.release()  # releasing twice is harmless


@pytest.mark.unit
async def test_a_manual_run_is_refused_while_another_run_holds_the_lock(session_factory) -> None:
    registry = AgentRegistry()
    registry.register("a", description="a")(type("A", (), {}))
    lock = PipelineLock(session_factory)
    launcher = PipelineLauncher(AsyncMock(), registry, lock)

    daily = await lock.acquire()  # the daily job is running
    with pytest.raises(PipelineBusyError):
        await launcher.launch(["AAPL"])
    await daily.release()

    await launcher.launch(["AAPL"])
    await asyncio.sleep(0.01)  # the run finished and gave the lock back
    assert launcher.active == 0
    held = await lock.acquire()
    assert held is not None
    await held.release()
