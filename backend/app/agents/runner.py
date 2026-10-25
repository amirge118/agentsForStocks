"""
AgentRunner — executes one agent for one symbol with the cross-cutting rules:

  1. idempotency — skip if a result already exists for (agent, symbol, market date)
  2. recall      — pull relevant memory from the knowledge store
  3. fetch → analyze → compliance review of the reasoning (app/agents/compliance.py)
  4. persist     — upsert the typed result (re-runs replace, never duplicate)
  5. learnings   — best-effort knowledge writes (never fail the run)
  6. audit       — every outcome, failures included, is recorded in agent_runs,
                   with phase timings and the run's LLM usage (tokens, cost, fallbacks)

Each run gets its own DB session, so agents can run concurrently.
"""

import logging
import time
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import Agent, AnalysisResult
from app.agents.compliance import apply_compliance
from app.core.clock import utcnow
from app.core.context import RunUsage, bind_run
from app.knowledge.store import KnowledgeStore
from app.models.agent_run import AgentRun
from app.observability import metrics
from app.repositories.agent_results import AgentResultRepository
from app.repositories.agent_runs import AgentRunRepository

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

RunStatus = Literal["completed", "skipped", "failed"]


@dataclass(frozen=True)
class RunOutcome:
    agent: str
    symbol: str
    run_id: str
    status: RunStatus
    result: AnalysisResult | None = None
    error: str | None = None
    usage: RunUsage | None = None


class AgentRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        knowledge: KnowledgeStore,
    ) -> None:
        self._session_factory = session_factory
        self._knowledge = knowledge

    async def run(
        self,
        agent: Agent,
        symbol: str,
        run_date: date,
        *,
        force: bool = False,
        pipeline_run_id: str | None = None,
    ) -> RunOutcome:
        run_id = str(uuid4())
        started_at = utcnow()
        timings = _Timings()
        # Every log line and LLM call inside the block carries these ids
        with (
            bind_run(
                pipeline_run_id=pipeline_run_id, run_id=run_id, agent=agent.name, symbol=symbol
            ) as usage,
            tracer.start_as_current_span(
                "agent.run",
                attributes={"agent": agent.name, "symbol": symbol, "run_id": run_id},
            ) as span,
        ):
            logger.info("Agent run started")
            outcome = await self._execute(agent, symbol, run_date, run_id, force, timings)
            if outcome.status == "completed" and outcome.result is not None:
                for learning in agent.learnings(symbol, outcome.result):
                    await self._knowledge.store(symbol, agent.name, learning)
                logger.info(
                    "Agent run completed",
                    extra={
                        "signal": outcome.result.signal,
                        "duration_ms": _ms_since(started_at),
                        "fetch_ms": timings.fetch_ms,
                        "analyze_ms": timings.analyze_ms,
                        **_usage_fields(usage),
                    },
                )
            await self._record(outcome, run_date, started_at, pipeline_run_id, timings, usage)
            _observe(span, agent.name, outcome.status, _ms_since(started_at), usage, outcome.error)
        return replace(outcome, usage=usage)

    async def _execute(
        self,
        agent: Agent,
        symbol: str,
        run_date: date,
        run_id: str,
        force: bool,
        timings: "_Timings",
    ) -> RunOutcome:
        try:
            async with self._session_factory() as session:
                repo = AgentResultRepository(session)
                if not force and await repo.exists(agent.name, symbol, run_date):
                    logger.info("Agent run skipped — already ran today")
                    return RunOutcome(agent.name, symbol, run_id, "skipped")

                memory = await self._knowledge.recall(symbol, agent.name)
                phase = time.perf_counter()
                with tracer.start_as_current_span("agent.fetch"):
                    data = await agent.fetch(symbol, run_date)
                timings.fetch_ms = _ms(phase)
                phase = time.perf_counter()
                with tracer.start_as_current_span("agent.analyze"):
                    analysed = await agent.analyze(symbol, data, memory)
                timings.analyze_ms = _ms(phase)
                result = apply_compliance(agent.name, symbol, analysed)

                await repo.upsert(
                    agent_type=agent.name,
                    symbol=symbol,
                    run_date=run_date,
                    run_id=run_id,
                    result=result.model_dump(mode="json"),
                )
                await session.commit()
                return RunOutcome(agent.name, symbol, run_id, "completed", result=result)
        except Exception as exc:
            logger.error("Agent run failed", extra={"error": str(exc)}, exc_info=True)
            return RunOutcome(agent.name, symbol, run_id, "failed", error=str(exc))

    async def _record(
        self,
        outcome: RunOutcome,
        run_date: date,
        started_at: datetime,
        pipeline_run_id: str | None,
        timings: "_Timings",
        usage: RunUsage,
    ) -> None:
        """Audit-trail write. A failure here is logged but never masks the run's outcome."""
        try:
            async with self._session_factory() as session:
                AgentRunRepository(session).add(
                    AgentRun(
                        run_id=outcome.run_id,
                        pipeline_run_id=pipeline_run_id,
                        agent_type=outcome.agent,
                        symbol=outcome.symbol,
                        run_date=run_date,
                        status=outcome.status,
                        error=outcome.error,
                        started_at=started_at,
                        finished_at=utcnow(),
                        fetch_ms=timings.fetch_ms,
                        analyze_ms=timings.analyze_ms,
                        llm_calls=usage.llm_calls,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cost_usd=_cost(usage),
                        llm_fallbacks=usage.llm_fallbacks,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.error("Could not record agent run", extra={"error": str(exc)})


@dataclass
class _Timings:
    fetch_ms: int | None = None
    analyze_ms: int | None = None


def _ms(since: float) -> int:
    return round((time.perf_counter() - since) * 1000)


def _ms_since(started_at: datetime) -> int:
    return round((utcnow() - started_at).total_seconds() * 1000)


def _cost(usage: RunUsage) -> float | None:
    """None when no call was priced (unknown model), so 0 never means 'unknown'."""
    if usage.llm_calls and not usage.cost_complete and usage.cost_usd == 0:
        return None
    return round(usage.cost_usd, 6)


def _observe(
    span: trace.Span,
    agent: str,
    status: str,
    duration_ms: int,
    usage: RunUsage,
    error: str | None,
) -> None:
    """Span attributes and metrics for one finished agent run."""
    span.set_attribute("agent.status", status)
    for key, value in _usage_fields(usage).items():
        if value is not None:
            span.set_attribute(f"llm.{key}" if key != "llm_calls" else key, value)
    if status == "failed":
        span.set_status(Status(StatusCode.ERROR, error))
    attrs = {"agent": agent, "status": status}
    metrics.agent_runs.add(1, attrs)
    metrics.agent_run_duration.record(duration_ms, attrs)
    if usage.llm_fallbacks:
        metrics.agent_fallbacks.add(usage.llm_fallbacks, {"agent": agent})


def _usage_fields(usage: RunUsage) -> dict[str, object]:
    return {
        "llm_calls": usage.llm_calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": _cost(usage),
        "llm_fallbacks": usage.llm_fallbacks,
    }


class SessionResultsReader:
    """ResultsReader backed by short-lived sessions (used by the recommendation agent)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_for_date(
        self, symbol: str, run_date: date, agent_types: list[str]
    ) -> dict[str, dict]:
        async with self._session_factory() as session:
            return await AgentResultRepository(session).get_for_date(symbol, run_date, agent_types)
