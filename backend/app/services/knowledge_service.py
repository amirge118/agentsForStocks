"""
Knowledge service — wraps OpenViking for agent context recall and pattern storage.

All public methods are async. The OpenViking client is sync and runs in a thread
via asyncio.to_thread() to avoid blocking the event loop.

OPENVIKING_ENABLED=false disables all calls (used in unit tests).
Store failures are always swallowed — a knowledge write must never crash an agent run.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import openviking as ov

logger = logging.getLogger(__name__)

# URIs follow the OpenViking filesystem convention
_URI_PATTERNS = "viking://agent/memories/patterns/"
_URI_CASES = "viking://agent/memories/cases/"
_URI_ENTITIES = "viking://agent/memories/entities/"
_URI_RESOURCES = "viking://resources/"
_URI_SKILLS = "viking://agent/skills/"

_RECALL_SCORE_THRESHOLD = 0.60  # minimum relevance score to include in recall
_RECALL_MAX_RESULTS = 5


class KnowledgeService:
    """
    Provides two integration points for AgentBase:

    1. recall_for_symbol() — called BEFORE fetch_data()
       Returns a list of plain-text observations to inject into the analysis prompt.

    2. store_pattern() / store_analysis_result() — called AFTER store_result()
       Deposits learnings into OpenViking. Failures are logged, never raised.

    Usage:
        knowledge = KnowledgeService()
        await FastAPI Depends injection ...
    """

    def __init__(self) -> None:
        self._client: "ov.SyncHTTPClient | None" = None

    def _get_client(self) -> "ov.SyncHTTPClient":
        import openviking as ov_mod
        from app.core.config import settings

        if self._client is None:
            self._client = ov_mod.SyncHTTPClient(
                url=settings.openviking_url,
                api_key=settings.openviking_api_key or None,
            )
            self._client.initialize()
        return self._client

    # ------------------------------------------------------------------
    # Recall — called before agent analysis
    # ------------------------------------------------------------------

    async def recall_for_symbol(self, symbol: str, agent_type: str) -> list[str]:
        """
        Search Memory for patterns relevant to this symbol + agent type.
        Returns up to 5 plain-text observations, filtered by relevance score.
        Returns [] if OPENVIKING_ENABLED=false or on any error.
        """
        from app.core.config import settings

        if not settings.openviking_enabled:
            return []

        query = f"{symbol} {agent_type} analysis patterns"

        def _recall() -> list[str]:
            client = self._get_client()
            results = client.find(query, target_uri=_URI_PATTERNS)
            return [
                r.abstract or r.snippet
                for r in results.resources[:_RECALL_MAX_RESULTS]
                if (r.score or 0.0) > _RECALL_SCORE_THRESHOLD
            ]

        try:
            return await asyncio.to_thread(_recall)
        except Exception as exc:
            logger.warning("OpenViking recall failed", extra={"symbol": symbol, "error": str(exc)})
            return []

    # ------------------------------------------------------------------
    # Store — called after agent analysis is complete and result is in DB
    # ------------------------------------------------------------------

    async def store_analysis_result(
        self, symbol: str, summary: str, agent_type: str
    ) -> None:
        """
        Store the analysis summary as a Case entry.
        Cases are immutable audit records — one per agent run.
        """
        await self._safe_write(
            uri=f"{_URI_CASES}{agent_type}/{symbol}/",
            content=summary,
            tags=[symbol, agent_type, "case"],
        )

    async def store_pattern(
        self, symbol: str, pattern: str, tags: list[str] | None = None
    ) -> None:
        """
        Store a discovered behavioral pattern for a symbol.
        Call this from agent subclasses when a noteworthy signal is detected.

        Example:
            await self.knowledge.store_pattern(
                symbol="AAPL",
                pattern="IV spikes 3-5 days before earnings consistently",
                tags=["earnings", "iv", "options"],
            )
        """
        await self._safe_write(
            uri=f"{_URI_PATTERNS}{symbol}/",
            content=pattern,
            tags=[symbol, "pattern"] + (tags or []),
        )

    async def store_entity(self, symbol: str, fact: str) -> None:
        """
        Store a static fact about a symbol that rarely changes.
        E.g. fiscal year end, reporting schedule quirks, share class notes.
        """
        await self._safe_write(
            uri=f"{_URI_ENTITIES}{symbol}/",
            content=fact,
            tags=[symbol, "entity"],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_write(
        self, uri: str, content: str, tags: list[str]
    ) -> None:
        """Write to OpenViking. Swallows all errors — never raises."""
        from app.core.config import settings

        if not settings.openviking_enabled:
            return

        def _write() -> None:
            client = self._get_client()
            client.add_resource(
                uri=uri,
                content=content,
                metadata={"tags": tags},
            )

        try:
            await asyncio.to_thread(_write)
        except Exception as exc:
            logger.warning(
                "OpenViking write failed — knowledge not stored",
                extra={"uri": uri, "error": str(exc)},
            )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

_knowledge_service_singleton: KnowledgeService | None = None


def get_knowledge_service() -> KnowledgeService:
    """FastAPI dependency. Returns a shared singleton."""
    global _knowledge_service_singleton
    if _knowledge_service_singleton is None:
        _knowledge_service_singleton = KnowledgeService()
    return _knowledge_service_singleton
