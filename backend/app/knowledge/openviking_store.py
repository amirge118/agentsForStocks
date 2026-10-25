"""
OpenViking-backed KnowledgeStore. The OpenViking client is synchronous, so calls
run in a worker thread. All errors are logged and swallowed.
"""

import asyncio
import logging
from typing import Any

from app.knowledge.store import Learning

logger = logging.getLogger(__name__)

_URI_PATTERNS = "viking://agent/memories/patterns/"
_URI_CASES = "viking://agent/memories/cases/"
_RECALL_SCORE_THRESHOLD = 0.60
_RECALL_MAX_RESULTS = 5


class OpenVikingStore:
    def __init__(self, url: str, api_key: str | None) -> None:
        self._url = url
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openviking  # optional dependency — only needed when enabled

            self._client = openviking.SyncHTTPClient(url=self._url, api_key=self._api_key)
            self._client.initialize()
        return self._client

    async def recall(self, symbol: str, agent_type: str) -> list[str]:
        def _find() -> list[str]:
            results = self._get_client().find(
                f"{symbol} {agent_type} analysis patterns", target_uri=_URI_PATTERNS
            )
            return [
                r.abstract or r.snippet
                for r in results.resources[:_RECALL_MAX_RESULTS]
                if (r.score or 0.0) > _RECALL_SCORE_THRESHOLD
            ]

        try:
            return await asyncio.to_thread(_find)
        except Exception as exc:
            logger.warning("OpenViking recall failed", extra={"symbol": symbol, "error": str(exc)})
            return []

    async def store(self, symbol: str, agent_type: str, learning: Learning) -> None:
        if not learning.content:
            return
        uri = (
            f"{_URI_CASES}{agent_type}/{symbol}/"
            if learning.kind == "case"
            else f"{_URI_PATTERNS}{symbol}/"
        )
        tags = [symbol, agent_type, learning.kind, *learning.tags]

        def _write() -> None:
            self._get_client().add_resource(
                uri=uri, content=learning.content, metadata={"tags": tags}
            )

        try:
            await asyncio.to_thread(_write)
        except Exception as exc:
            logger.warning("OpenViking write failed", extra={"uri": uri, "error": str(exc)})
