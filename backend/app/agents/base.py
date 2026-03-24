"""
AgentBase — the contract every stock analysis agent must implement.

Lifecycle per run:
  1. idempotency check          — skip if already ran for symbol + date
  2. recall_context()           — pull relevant patterns from OpenViking
  3. fetch_data(symbol)         — get raw data (yfinance, APIs)
  4. analyze(data, context)     — generate result using Claude + recalled context
  5. store_result()             — upsert to PostgreSQL
  6. store_learnings()          — deposit patterns/cases to OpenViking (never raises)
"""
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class AgentBase(ABC):
    # Subclasses must set this — used in logs, DB records, and knowledge URIs
    agent_type: str

    def __init__(self, db: AsyncSession, knowledge: KnowledgeService) -> None:
        self.db = db
        self.knowledge = knowledge

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, symbol: str) -> None:
        run_id = str(uuid4())
        log_ctx = {"agent": self.agent_type, "symbol": symbol, "run_id": run_id}

        logger.info("Agent run started", extra=log_ctx)

        try:
            if await self._is_duplicate(symbol):
                logger.info("Agent run skipped — already ran today", extra=log_ctx)
                return

            # Step 2: recall relevant patterns before fetching data
            prior_context: list[str] = await self.knowledge.recall_for_symbol(
                symbol=symbol, agent_type=self.agent_type
            )
            if prior_context:
                logger.debug(
                    "Recalled %d context items from knowledge base",
                    len(prior_context),
                    extra=log_ctx,
                )

            # Steps 3 & 4: fetch then analyze
            data = await self.fetch_data(symbol)
            result = await self.analyze(data, prior_context=prior_context)

            # Step 5: persist to PostgreSQL (source of truth)
            await self.store_result(symbol=symbol, run_id=run_id, result=result)

            # Step 6: deposit learnings (additive, never raises)
            await self.store_learnings(symbol=symbol, result=result)

            logger.info("Agent run completed", extra=log_ctx)

        except Exception as exc:
            logger.error(
                "Agent run failed",
                extra={**log_ctx, "error": str(exc)},
                exc_info=True,
            )
            raise

    # ------------------------------------------------------------------
    # Abstract methods — subclasses must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_data(self, symbol: str) -> dict:
        """Fetch raw data for the symbol (yfinance, APIs, etc.)."""
        ...

    @abstractmethod
    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        """
        Produce the analysis result.
        prior_context is a list of plain-text patterns recalled from OpenViking.
        Inject them into the Claude prompt as additional context.
        """
        ...

    # ------------------------------------------------------------------
    # Hooks with default implementations — subclasses can override
    # ------------------------------------------------------------------

    async def store_result(self, symbol: str, run_id: str, result: dict) -> None:
        """
        Upsert result to PostgreSQL.
        Unique constraint: (agent_type, symbol, run_date) — re-runs replace, not duplicate.
        Subclasses can override to use a different model, but must preserve idempotency.
        """
        from sqlalchemy.dialects.postgresql import insert
        from app.models.agent_result import AgentResult  # imported lazily to avoid circular deps

        stmt = (
            insert(AgentResult)
            .values(
                agent_type=self.agent_type,
                symbol=symbol,
                run_date=date.today(),
                run_id=run_id,
                result_json=result,
                updated_at=datetime.utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["agent_type", "symbol", "run_date"],
                set_={
                    "result_json": result,
                    "run_id": run_id,
                    "updated_at": datetime.utcnow(),
                },
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def store_learnings(self, symbol: str, result: dict) -> None:
        """
        Default: deposit the analysis summary as a Case in OpenViking.
        Override in subclasses to additionally call self.knowledge.store_pattern()
        when a noteworthy signal is detected.

        This method MUST NOT raise. Wrap all logic in try/except if overriding.
        """
        summary = result.get("summary", "")
        if summary:
            await self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=summary,
                agent_type=self.agent_type,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _is_duplicate(self, symbol: str) -> bool:
        """Return True if this agent already ran for symbol today."""
        from sqlalchemy import select
        from app.models.agent_result import AgentResult

        stmt = select(AgentResult.id).where(
            AgentResult.agent_type == self.agent_type,
            AgentResult.symbol == symbol,
            AgentResult.run_date == date.today(),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None
