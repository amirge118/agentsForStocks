"""
PipelineLauncher — starts pipeline runs in the background for API callers.

A full run takes minutes, so the API validates the request, starts the run as an
asyncio task and returns its pipeline_run_id immediately; progress is visible in
agent_runs. Tasks are tracked so they are not garbage-collected and can be
cancelled on shutdown. A run holds the PipelineLock, shared with the daily job,
so a manual run never overlaps a scheduled one — in any process.
"""

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from app.agents.registry import AgentRegistry
from app.core.clock import market_today
from app.core.symbols import validate_symbol
from app.pipeline.lock import HeldLock, PipelineLock
from app.pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)


class PipelineBusyError(Exception):
    """A pipeline run (manual or scheduled) is still in progress."""


@dataclass(frozen=True)
class LaunchedRun:
    pipeline_run_id: str
    run_date: date
    symbols: list[str]
    agents: list[str]
    force: bool


class PipelineLauncher:
    def __init__(
        self,
        orchestrator: PipelineOrchestrator,
        registry: AgentRegistry,
        lock: PipelineLock | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._registry = registry
        self._lock = lock
        self._tasks: set[asyncio.Task[object]] = set()

    async def launch(
        self,
        symbols: Iterable[str],
        agents: Iterable[str] | None = None,
        *,
        force: bool = False,
    ) -> LaunchedRun:
        """
        Validate synchronously (ValueError / KeyError), then start the run in the
        background. Only one run at a time (PipelineBusyError) so repeated clicks,
        or a click during the daily job, cannot multiply FMP / LLM spend.
        """
        if self._tasks:
            raise PipelineBusyError("A pipeline run is already in progress")
        tickers = list(dict.fromkeys(validate_symbol(s) for s in symbols))
        if not tickers:
            raise ValueError("At least one symbol is required")
        selected = list(agents) if agents is not None else None
        levels = self._registry.execution_levels(selected)  # raises KeyError for unknown agents
        held = await self._lock.acquire() if self._lock is not None else None
        if self._lock is not None and held is None:
            raise PipelineBusyError("A pipeline run is already in progress")

        run = LaunchedRun(
            pipeline_run_id=str(uuid4()),
            run_date=market_today(),
            symbols=tickers,
            agents=[name for level in levels for name in level],
            force=force,
        )
        task = asyncio.create_task(self._run(run, selected, held))
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        logger.info("Pipeline launched via API", extra={"pipeline_run_id": run.pipeline_run_id})
        return run

    async def _run(self, run: LaunchedRun, agents: list[str] | None, held: HeldLock | None) -> None:
        try:
            await self._orchestrator.run(
                run.symbols,
                agents=agents,
                force=run.force,
                run_date=run.run_date,
                pipeline_run_id=run.pipeline_run_id,
            )
        finally:
            if held is not None:
                await held.release()

    def _finished(self, task: asyncio.Task[object]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background pipeline crashed", exc_info=task.exception())

    @property
    def active(self) -> int:
        return len(self._tasks)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
