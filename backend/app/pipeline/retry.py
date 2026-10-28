"""
FailedRunRetry — a second chance, later the same day, for agent runs that failed.

A provider that is down at 18:30 (Yahoo, FMP, SEC) fails the agents that need it;
without a retry the day has no result for them, and the recommendation is made
without them. After the daily run, the failed (agent, symbol) pairs are run again
RETRY_DELAY later — together with every agent downstream of them (forced, since
they already ran on the missing input). At most `attempts` rounds; each round
holds the PipelineLock like any other run, and is recorded as its own job run.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from app.agents.registry import AgentRegistry
from app.core.clock import utcnow
from app.pipeline.lock import PipelineLock
from app.pipeline.orchestrator import PipelineOrchestrator, PipelineReport

logger = logging.getLogger(__name__)

RETRY_JOB_ID = "retry_failed_agents"
# The lock may be held by a manual run: wait for it rather than skip the retry
LOCK_WAIT_SECONDS = 2 * 3600.0

# scheduler.add_job, or anything with its signature that runs `func` at `run_date`
AddJob = Callable[..., Any]
JobRunner = Callable[..., Awaitable[Any]]


class FailedRunRetry:
    def __init__(
        self,
        orchestrator: PipelineOrchestrator,
        registry: AgentRegistry,
        add_job: AddJob,
        *,
        delay: timedelta = timedelta(minutes=30),
        attempts: int = 2,
        lock: PipelineLock | None = None,
        run_job: JobRunner | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._registry = registry
        self._add_job = add_job
        self._delay = delay
        self._attempts = attempts
        self._lock = lock
        self._run_job = run_job

    def plan(self, report: PipelineReport, attempt: int = 1) -> bool:
        """Schedule a retry of the report's failed runs; False when there is none to make."""
        failed = sorted({(o.agent, o.symbol) for o in report.failed})
        if not failed:
            return False
        if attempt > self._attempts:
            logger.error(
                "Agent runs still failing after every retry",
                extra={"failed": [f"{a}/{s}" for a, s in failed], "attempts": self._attempts},
            )
            return False
        args = (report.run_date, failed, attempt)
        func: Callable[..., Awaitable[Any]] = self.retry
        if self._run_job is not None:  # recorded as a job run
            func, args = self._run_job, (RETRY_JOB_ID, self.retry, *args)
        self._add_job(
            func,
            trigger="date",
            run_date=utcnow() + self._delay,
            args=list(args),
            id=f"{RETRY_JOB_ID}_{attempt}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.warning(
            "Failed agent runs will be retried",
            extra={
                "failed": [f"{a}/{s}" for a, s in failed],
                "attempt": attempt,
                "in_minutes": self._delay.total_seconds() / 60,
            },
        )
        return True

    async def retry(
        self, run_date: date, failed: list[tuple[str, str]], attempt: int
    ) -> PipelineReport:
        held = await self._lock.acquire(LOCK_WAIT_SECONDS) if self._lock is not None else None
        if self._lock is not None and held is None:
            raise RuntimeError("the pipeline lock stayed busy; retry not run")
        try:
            outcomes = []
            for symbol in sorted({s for _, s in failed}):
                agents = self._registry.downstream(a for a, s in failed if s == symbol)
                report = await self._orchestrator.run(
                    [symbol], agents=sorted(agents), force=True, run_date=run_date
                )
                outcomes.extend(report.outcomes)
        finally:
            if held is not None:
                await held.release()
        combined = PipelineReport(f"retry-{attempt}", run_date, tuple(outcomes))
        logger.info("Retry of failed agent runs finished", extra={"counts": combined.counts})
        self.plan(combined, attempt + 1)
        return combined
