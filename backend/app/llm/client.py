"""
LLMClient — the only place that calls the Anthropic API.

Replies are constrained with structured outputs (output_config.format, JSON
schema derived from the Pydantic model) and then validated by Pydantic, so
agents receive typed objects instead of scraping JSON out of free text.
Failures raise LLMError; the agent runner decides how to degrade.
"""

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.llm.mcp import MCP_BETA, McpServer, validate_servers
from app.llm.schema import output_schema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Claude could not produce a valid structured reply."""


# Remote MCP tool calls make a request far slower than a plain completion
_MCP_TIMEOUT_SECONDS = 120.0


class LLMClient:
    def __init__(self, client: anthropic.AsyncAnthropic, default_model: str) -> None:
        self._client = client
        self.default_model = default_model

    async def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
        max_tokens: int = 1024,
        mcp_servers: Sequence[McpServer] | None = None,
    ) -> T:
        """
        One structured completion. With mcp_servers, Claude may first call those
        servers' tools; the answer is the final text block of the response.
        """
        chosen = model or self.default_model
        servers = list(mcp_servers or [])
        validate_servers(servers)  # caller bug, not an LLM failure — let ValueError surface
        request: dict[str, Any] = {
            "model": chosen,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"format": {"type": "json_schema", "schema": output_schema(schema)}},
        }
        try:
            if servers:
                message = await self._client.with_options(
                    timeout=_MCP_TIMEOUT_SECONDS
                ).beta.messages.create(
                    **request,
                    betas=[MCP_BETA],
                    mcp_servers=[s.to_server_param() for s in servers],
                    tools=[s.to_toolset_param() for s in servers],
                )
            else:
                message = await self._client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"{chosen} returned HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"{chosen} unreachable: {exc}") from exc

        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMError(f"{chosen} stopped with {message.stop_reason}")

        # With MCP tools the content interleaves text and mcp_tool_use/result blocks
        texts = [block.text for block in message.content if block.type == "text"]
        text = texts[-1] if texts else ""
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("Claude reply failed schema validation: %.200s", text)
            raise LLMError(f"{chosen} reply did not match {schema.__name__}") from exc

    async def aclose(self) -> None:
        await self._client.close()
