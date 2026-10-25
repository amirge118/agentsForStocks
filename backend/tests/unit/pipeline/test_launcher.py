import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from app.agents.registry import AgentRegistry
from app.pipeline.launcher import PipelineBusyError, PipelineLauncher


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register("a", description="a")(type("A", (), {}))
    reg.register("b", description="b", depends_on=["a"])(type("B", (), {}))
    return reg


@pytest.mark.unit
async def test_launch_validates_then_runs_in_background() -> None:
    orchestrator = AsyncMock()
    launcher = PipelineLauncher(orchestrator, _registry())

    run = launcher.launch(["aapl", "AAPL", "msft"], force=True)
    assert run.symbols == ["AAPL", "MSFT"]
    assert run.agents == ["a", "b"]
    assert launcher.active == 1
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    kwargs = orchestrator.run.await_args.kwargs
    assert kwargs["pipeline_run_id"] == run.pipeline_run_id
    assert kwargs["force"] is True
    assert launcher.active == 0


@pytest.mark.unit
def test_launch_rejects_bad_input_without_starting() -> None:
    orchestrator = AsyncMock()
    launcher = PipelineLauncher(orchestrator, _registry())
    with pytest.raises(ValueError):
        launcher.launch([])
    with pytest.raises(ValueError):
        launcher.launch(["BAD;"])
    with pytest.raises(KeyError):
        launcher.launch(["AAPL"], ["zzz"])
    orchestrator.run.assert_not_called()


@pytest.mark.unit
async def test_crashed_run_is_logged_and_aclose_cancels(caplog) -> None:
    orchestrator = AsyncMock()
    orchestrator.run.side_effect = RuntimeError("boom")
    launcher = PipelineLauncher(orchestrator, _registry())
    launcher.launch(["AAPL"])
    await asyncio.sleep(0.01)
    assert "Background pipeline crashed" in caplog.text

    async def hang(*args, **kwargs) -> None:
        await asyncio.sleep(10)

    orchestrator.run.side_effect = hang
    launcher.launch(["AAPL"])
    await asyncio.sleep(0)
    with caplog.at_level(logging.ERROR):
        await launcher.aclose()
    assert launcher.active == 0


@pytest.mark.unit
async def test_only_one_manual_run_at_a_time() -> None:
    gate = asyncio.Event()
    orchestrator = AsyncMock()

    async def slow(*args, **kwargs) -> None:
        await gate.wait()

    orchestrator.run.side_effect = slow
    launcher = PipelineLauncher(orchestrator, _registry())
    launcher.launch(["AAPL"])
    with pytest.raises(PipelineBusyError):
        launcher.launch(["MSFT"])
    gate.set()
    await asyncio.sleep(0.01)
    launcher.launch(["MSFT"])  # allowed again once the first finished
    await launcher.aclose()
