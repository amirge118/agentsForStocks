"""
AgentRunner — executes one agent for one symbol with the cross-cutting rules:

  1. idempotency — skip if a result already exists for (agent, symbol, market date)
  2. recall      — pull relevant memory from the knowledge store
  3. fetch → analyze
  4. persist     — upsert the typed result (re-runs replace, never duplicate)
  5. learnings   — best-effort knowledge writes (never fail the run)

Each run gets its own DB session, so agents can run concurrently.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import Agent, AnalysisResult
from app.knowledge.store import KnowledgeStore
from app.repositories.agent_results import AgentResultRepository

logger = logging.getLogger(__name__)

RunStatus = Literal["completed", "skipped", "failed"]


@dataclass(frozen=True)
class RunOutcome:
    agent: str
    symbol: str
    run_id: str
    status: RunStatus
    result: AnalysisResult | None = None
    error: str | None = None


class AgentRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        knowledge: KnowledgeStore,
    ) -> None:
        self._session_factory = session_factory
        self._knowledge = knowledge

    async def run(
        self, agent: Agent, symbol: str, run_date: date, *, force: bool = False
    ) -> RunOutcome:
        run_id = str(uuid4())
        ctx = {"agent": agent.name, "symbol": symbol, "run_id": run_id}
        logger.info("Agent run started", extra=ctx)

        try:
            async with self._session_factory() as session:
                repo = AgentResultRepository(session)
                if not force and await repo.exists(agent.name, symbol, run_date):
                    logger.info("Agent run skipped — already ran today", extra=ctx)
                    return RunOutcome(agent.name, symbol, run_id, "skipped")

                memory = await self._knowledge.recall(symbol, agent.name)
                data = await agent.fetch(symbol, run_date)
                result = await agent.analyze(symbol, data, memory)

                await repo.upsert(
                    agent_type=agent.name,
                    symbol=symbol,
                    run_date=run_date,
                    run_id=run_id,
                    result=result.model_dump(mode="json"),
                )
                await session.commit()
        except Exception as exc:
            logger.error("Agent run failed", extra={**ctx, "error": str(exc)}, exc_info=True)
            return RunOutcome(agent.name, symbol, run_id, "failed", error=str(exc))

        for learning in agent.learnings(symbol, result):
            await self._knowledge.store(symbol, agent.name, learning)

        logger.info("Agent run completed", extra={**ctx, "signal": result.signal})
        return RunOutcome(agent.name, symbol, run_id, "completed", result=result)


class SessionResultsReader:
    """ResultsReader backed by short-lived sessions (used by the recommendation agent)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_for_date(
        self, symbol: str, run_date: date, agent_types: list[str]
    ) -> dict[str, dict]:
        async with self._session_factory() as session:
            return await AgentResultRepository(session).get_for_date(symbol, run_date, agent_types)
