"""
OpenAICompatibleClient — a second, cheaper LLM provider behind the same
generate() interface as LLMClient, for any service that speaks the OpenAI
chat-completions API with JSON-schema structured outputs:

  Google Gemini   https://generativelanguage.googleapis.com/v1beta/openai   (free tier)
  OpenRouter      https://openrouter.ai/api/v1                             (many models)
  DeepSeek        https://api.deepseek.com/v1
  Ollama (local)  http://localhost:11434/v1                                (no key, $0)
  Groq            https://api.groq.com/openai/v1                          (free tier)
  Cerebras        https://api.cerebras.ai/v1                              (free tier)

Calls go through the same CallTracker as Claude: tokens, cost, latency, the
exact prompt and reply land in llm_calls, and the agent run's usage is updated.
Transient failures (timeouts, 5xx) are retried with backoff.

With a ProviderQuota (the free tiers, app/llm/quota.py) a request is only sent
when it fits the provider's limits, and a 429 is not retried: the provider is
cooled down for its Retry-After and the call fails at once, so a FallbackChain
can try the next provider. structured_mode="json_object" is for services whose
strict JSON-schema mode is missing or unreliable: the schema goes in the system
prompt and the reply is validated by Pydantic all the same.
"""

import json
import logging
from collections.abc import Sequence
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel

from app.llm.errors import QuotaExhaustedError
from app.llm.mcp import McpServer
from app.llm.pricing import Price, TokenUsage
from app.llm.provider import ALT
from app.llm.quota import ProviderQuota, estimate_tokens
from app.llm.recording import LLMCallRecorder, NullRecorder
from app.llm.schema import output_schema
from app.llm.tracking import CallTracker
from app.providers.errors import ProviderError, RetryableError
from app.providers.retry import RETRYABLE_STATUS, RetryPolicy, with_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Without a Retry-After header, leave a rate-limited free tier alone for this long
_DEFAULT_COOLDOWN_SECONDS = 60.0

StructuredMode = Literal["json_schema", "json_object"]


class _RateLimitedError(ProviderError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"HTTP 429 (retry after {retry_after:.0f}s)")
        self.retry_after = retry_after


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_model: str,
        name: str = ALT,
        structured_mode: StructuredMode = "json_schema",
        extra_body: dict[str, Any] | None = None,
        quota: ProviderQuota | None = None,
        reasoning_tokens: int = 0,
        recorder: LLMCallRecorder | None = None,
        capture_content: bool = True,
        prices: dict[str, Price] | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.default_model = default_model
        self.name = name
        self.structured_mode = structured_mode
        self._extra_body = dict(extra_body or {})
        self.quota = quota
        # Reasoning models (gpt-oss) spend output tokens thinking before the JSON;
        # this is added to every call's budget so the answer isn't cut off
        self._reasoning_tokens = reasoning_tokens
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
        budget = max_tokens + self._reasoning_tokens
        slot = None
        if self.quota is not None:
            slot = await self.quota.acquire(estimate_tokens(system, prompt, budget))
            if slot is None:
                raise QuotaExhaustedError(f"{self.name} quota has no room for this request")
        call = CallTracker(
            recorder=self._recorder,
            model=chosen,
            system=system,  # the prompt version stays the same whichever mode sends it
            prompt=prompt,
            prompt_name=prompt_name,
            capture_content=self._capture_content,
            prices=self._prices,
            provider=self.name,
        )
        body = {
            **self._extra_body,
            "model": chosen,
            "max_tokens": budget,
            "messages": [
                {"role": "system", "content": self._system_text(system, schema)},
                {"role": "user", "content": prompt},
            ],
            "response_format": self._response_format(schema),
        }
        try:
            payload = await with_retry(lambda: self._post(body), self._retry, label=f"LLM {chosen}")
        except _RateLimitedError as exc:
            if self.quota is not None:
                self.quota.cool_down(exc.retry_after)
            raise await call.fail(
                f"{self.name} {chosen} rate limited: {exc}", exc_type=QuotaExhaustedError
            ) from exc
        except ProviderError as exc:
            raise await call.fail(f"{chosen} request failed: {exc}") from exc

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
        if slot is not None and self.quota is not None:
            self.quota.settle(slot, call.usage.total_input + call.usage.output_tokens)
        return await call.parse(
            schema,
            _strip_fences(text),
            cut_off=choice.get("finish_reason") in ("length", "content_filter"),
        )

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        if self.structured_mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": output_schema(schema),
                "strict": True,
            },
        }

    def _system_text(self, system: str, schema: type[BaseModel]) -> str:
        if self.structured_mode != "json_object":
            return system
        spec = json.dumps(output_schema(schema), separators=(",", ":"))
        return (
            f"{system}\n\nRespond with a single JSON object, no other text, "
            f"that matches this JSON schema:\n{spec}"
        )

    async def list_models(self) -> list[str]:
        """Model ids the service offers (GET /models) — the preflight checks against it."""
        payload = await with_retry(self._get_models, self._retry, label=f"{self.name} models")
        ids = (str(m.get("id")) for m in payload.get("data") or [] if m.get("id"))
        return sorted(i.removeprefix("models/") for i in ids)  # Gemini lists "models/<id>"

    async def _get_models(self) -> dict[str, Any]:
        try:
            resp = await self._http.get("/models")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(type(exc).__name__) from exc
        return self._decode(resp)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._http.post("/chat/completions", json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(type(exc).__name__) from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429 and self.quota is not None:
            raise _RateLimitedError(_retry_after(resp))
        if resp.status_code in RETRYABLE_STATUS:
            raise RetryableError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return dict(resp.json())
        except json.JSONDecodeError as exc:
            raise ProviderError("response is not JSON") from exc

    def price(self, model: str) -> Price | None:
        return (self._prices or {}).get(model)

    async def aclose(self) -> None:
        await self._http.aclose()


def _retry_after(resp: httpx.Response) -> float:
    try:
        return max(1.0, float(resp.headers.get("retry-after", "")))
    except ValueError:
        return _DEFAULT_COOLDOWN_SECONDS


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()
