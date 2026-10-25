"""
OpenAICompatibleClient — a second, cheaper LLM provider behind the same
generate() interface as LLMClient, for any service that speaks the OpenAI
chat-completions API with JSON-schema structured outputs:

  Google Gemini   https://generativelanguage.googleapis.com/v1beta/openai   (free tier)
  OpenRouter      https://openrouter.ai/api/v1                             (many models)
  DeepSeek        https://api.deepseek.com/v1
  Ollama (local)  http://localhost:11434/v1                                (no key, $0)

Calls go through the same CallTracker as Claude: tokens, cost, latency, the
exact prompt and reply land in llm_calls, and the agent run's usage is updated.
Transient failures (timeouts, 429, 5xx) are retried with backoff.
"""

import json
import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.client import LLMError
from app.llm.mcp import McpServer
from app.llm.pricing import Price, TokenUsage
from app.llm.recording import LLMCallRecorder, NullRecorder
from app.llm.schema import output_schema
from app.llm.tracking import CallTracker
from app.providers.errors import ProviderError, RetryableError
from app.providers.retry import RetryPolicy, with_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_model: str,
        recorder: LLMCallRecorder | None = None,
        capture_content: bool = True,
        prices: dict[str, Price] | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.default_model = default_model
        self._recorder = recorder or NullRecorder()
        self._capture_content = capture_content
        self._prices = prices
        self._retry = retry_policy or RetryPolicy(max_attempts=3, timeout_seconds=timeout_seconds)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

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
        if mcp_servers:
            raise ValueError("MCP servers are only supported with the Anthropic provider")
        chosen = model or self.default_model
        call = CallTracker(
            recorder=self._recorder,
            model=chosen,
            system=system,
            prompt=prompt,
            prompt_name=prompt_name,
            capture_content=self._capture_content,
            prices=self._prices,
        )
        body = {
            "model": chosen,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": output_schema(schema),
                    "strict": True,
                },
            },
        }
        try:
            payload = await with_retry(lambda: self._post(body), self._retry, label=f"LLM {chosen}")
        except ProviderError as exc:
            error = f"{chosen} request failed: {exc}"
            await call.finish("error", error=error)
            raise LLMError(error) from exc

        choice = (payload.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = payload.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        call.observe(
            TokenUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0) - int(cached),
                output_tokens=int(usage.get("completion_tokens") or 0),
                cache_read_tokens=int(cached),
            ),
            stop_reason=choice.get("finish_reason"),
            response=text,
            request_id=payload.get("id"),
        )
        if choice.get("finish_reason") in ("length", "content_filter"):
            error = f"{chosen} stopped with {choice.get('finish_reason')}"
            await call.finish("error", error=error)
            raise LLMError(error)
        try:
            result = schema.model_validate_json(_strip_fences(text))
        except ValidationError as exc:
            logger.warning("Model reply failed schema validation: %.200s", text)
            error = f"{chosen} reply did not match {schema.__name__}"
            await call.finish("error", error=error)
            raise LLMError(error) from exc
        await call.finish("ok")
        return result

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._http.post("/chat/completions", json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(type(exc).__name__) from exc
        if resp.status_code in _RETRYABLE_STATUS:
            raise RetryableError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return dict(resp.json())
        except json.JSONDecodeError as exc:
            raise ProviderError("response is not JSON") from exc

    async def aclose(self) -> None:
        await self._http.aclose()


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()
