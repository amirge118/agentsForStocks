"""
LLMClient — the only place that calls the Anthropic API.

Replies are constrained with structured outputs (output_config.format, JSON
schema derived from the Pydantic model) and then validated by Pydantic, so
agents receive typed objects instead of scraping JSON out of free text.
Failures raise LLMError; the agent runner decides how to degrade.

Every request — success or failure — produces an LLMCallRecord (tokens, cost,
latency, prompt version, and the exact text when capture is on). It is logged,
stored through the recorder, and added to the current agent run's usage.
"""

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.llm.mcp import MCP_BETA, McpServer, validate_servers
from app.llm.pricing import Price, TokenUsage
from app.llm.recording import (
    LLMCallRecorder,
    NullRecorder,
)
from app.llm.schema import output_schema
from app.llm.tracking import CallTracker

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Claude could not produce a valid structured reply."""


# Remote MCP tool calls make a request far slower than a plain completion
_MCP_TIMEOUT_SECONDS = 120.0


class LLMClient:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        default_model: str,
        *,
        recorder: LLMCallRecorder | None = None,
        capture_content: bool = True,
        prices: dict[str, Price] | None = None,
    ) -> None:
        self._client = client
        self.default_model = default_model
        self._recorder = recorder or NullRecorder()
        self._capture_content = capture_content
        self._prices = prices

    async def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
        max_tokens: int = 1024,
        mcp_servers: Sequence[McpServer] | None = None,
        prompt_name: str | None = None,
    ) -> T:
        """
        One structured completion. With mcp_servers, Claude may first call those
        servers' tools; the answer is the final text block of the response.
        prompt_name labels the call in the ledger (usually the prompt file's name).
        """
        chosen = model or self.default_model
        servers = list(mcp_servers or [])
        validate_servers(servers)  # caller bug, not an LLM failure — let ValueError surface
        call = CallTracker(
            recorder=self._recorder,
            model=chosen,
            system=system,
            prompt=prompt,
            prompt_name=prompt_name,
            capture_content=self._capture_content,
            prices=self._prices,
            provider="anthropic",
        )
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
            error = f"{chosen} returned HTTP {exc.status_code}: {exc.message}"
            await call.finish("error", error=error, request_id=getattr(exc, "request_id", None))
            raise LLMError(error) from exc
        except anthropic.APIConnectionError as exc:
            error = f"{chosen} unreachable: {exc}"
            await call.finish("error", error=error)
            raise LLMError(error) from exc

        # With MCP tools the content interleaves text and mcp_tool_use/result blocks
        texts = [block.text for block in message.content if block.type == "text"]
        text = texts[-1] if texts else ""
        usage = getattr(message, "usage", None)
        request_id = getattr(message, "_request_id", None)
        call.observe(
            TokenUsage(
                input_tokens=_int(usage, "input_tokens"),
                output_tokens=_int(usage, "output_tokens"),
                cache_read_tokens=_int(usage, "cache_read_input_tokens"),
                cache_write_tokens=_int(usage, "cache_creation_input_tokens"),
            ),
            stop_reason=message.stop_reason,
            response=text,
            request_id=request_id if isinstance(request_id, str) else None,
        )

        if message.stop_reason in ("refusal", "max_tokens"):
            error = f"{chosen} stopped with {message.stop_reason}"
            await call.finish("error", error=error)
            raise LLMError(error)
        try:
            result = schema.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("Claude reply failed schema validation: %.200s", text)
            error = f"{chosen} reply did not match {schema.__name__}"
            await call.finish("error", error=error)
            raise LLMError(error) from exc
        await call.finish("ok")
        return result

    async def aclose(self) -> None:
        await self._client.close()


def _int(obj: Any, name: str) -> int:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else 0
