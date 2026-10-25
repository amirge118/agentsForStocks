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
import time
from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import uuid4

import anthropic
from pydantic import BaseModel, ValidationError

from app.core.clock import utcnow
from app.core.context import current_fields, current_usage
from app.llm.mcp import MCP_BETA, McpServer, validate_servers
from app.llm.pricing import Price, TokenUsage, cost_usd
from app.llm.recording import (
    CallStatus,
    LLMCallRecord,
    LLMCallRecorder,
    NullRecorder,
    prompt_version,
)
from app.llm.schema import output_schema

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
        call = _Call(self, chosen, system, prompt, prompt_name)
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
        call.observe(message, text)

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


class _Call:
    """Bookkeeping for one generate() call: timing, usage, and the final record."""

    def __init__(
        self, client: LLMClient, model: str, system: str, prompt: str, prompt_name: str | None
    ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self._prompt = prompt
        self._prompt_name = prompt_name
        self._started = time.perf_counter()
        self._usage = TokenUsage()
        self._stop_reason: str | None = None
        self._request_id: str | None = None
        self._response: str | None = None

    def observe(self, message: Any, text: str) -> None:
        """Take usage, stop reason and request id from the API response."""
        usage = getattr(message, "usage", None)
        self._usage = TokenUsage(
            input_tokens=_int(usage, "input_tokens"),
            output_tokens=_int(usage, "output_tokens"),
            cache_read_tokens=_int(usage, "cache_read_input_tokens"),
            cache_write_tokens=_int(usage, "cache_creation_input_tokens"),
        )
        self._stop_reason = getattr(message, "stop_reason", None)
        request_id = getattr(message, "_request_id", None)
        self._request_id = request_id if isinstance(request_id, str) else None
        self._response = text

    async def finish(
        self, status: CallStatus, *, error: str | None = None, request_id: str | None = None
    ) -> None:
        latency_ms = round((time.perf_counter() - self._started) * 1000)
        cost = cost_usd(self._model, self._usage, self._client._prices)
        fields = current_fields()
        capture = self._client._capture_content
        record = LLMCallRecord(
            call_id=str(uuid4()),
            created_at=utcnow(),
            model=self._model,
            prompt_name=self._prompt_name,
            prompt_version=prompt_version(self._system),
            status=status,
            latency_ms=latency_ms,
            usage=self._usage,
            cost_usd=cost,
            stop_reason=self._stop_reason,
            error=error,
            request_id=request_id or self._request_id,
            pipeline_run_id=fields.get("pipeline_run_id"),
            run_id=fields.get("run_id"),
            agent=fields.get("agent"),
            symbol=fields.get("symbol"),
            system_prompt=self._system if capture else None,
            prompt=self._prompt if capture else None,
            response=self._response if capture else None,
        )
        _log(record)
        _accumulate(record)
        await self._client._recorder.record(record)


def _int(obj: Any, name: str) -> int:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else 0


def _log(record: LLMCallRecord) -> None:
    extra = {
        "call_id": record.call_id,
        "model": record.model,
        "prompt_name": record.prompt_name,
        "prompt_version": record.prompt_version,
        "llm_status": record.status,
        "input_tokens": record.usage.input_tokens,
        "output_tokens": record.usage.output_tokens,
        "cache_read_tokens": record.usage.cache_read_tokens,
        "cache_write_tokens": record.usage.cache_write_tokens,
        "cost_usd": record.cost_usd,
        "latency_ms": record.latency_ms,
        "stop_reason": record.stop_reason,
    }
    if record.status == "ok":
        logger.info("LLM call completed", extra=extra)
    else:
        logger.warning("LLM call failed", extra={**extra, "error": record.error})


def _accumulate(record: LLMCallRecord) -> None:
    usage = current_usage()
    if usage is None:
        return
    usage.llm_calls += 1
    usage.input_tokens += record.usage.total_input
    usage.output_tokens += record.usage.output_tokens
    if record.cost_usd is None:
        usage.cost_complete = False
    else:
        usage.cost_usd += record.cost_usd
