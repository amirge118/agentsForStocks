"""
LLMRouter — what agents call. Sends each request to the provider its profile
names: "anthropic" (Claude, LLMClient) or "alt" (an OpenAI-compatible service,
OpenAICompatibleClient). An unconfigured provider raises LLMError, so the agent
falls back to its own signal and the miss is counted like any other outage.
"""

from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.llm.client import LLMError
from app.llm.mcp import McpServer

T = TypeVar("T", bound=BaseModel)

ANTHROPIC = "anthropic"
ALT = "alt"


class LLMProvider(Protocol):
    default_model: str

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
    ) -> T: ...

    async def aclose(self) -> None: ...


class LLMRouter:
    def __init__(
        self, providers: dict[str, LLMProvider], default_provider: str = ANTHROPIC
    ) -> None:
        self._providers = providers
        self.default_provider = default_provider

    def configured(self, provider: str) -> bool:
        return provider in self._providers

    def default_model(self, provider: str | None = None) -> str | None:
        client = self._providers.get(provider or self.default_provider)
        return client.default_model if client is not None else None

    async def generate(self, *, provider: str | None = None, **kwargs: Any) -> Any:
        name = provider or self.default_provider
        client = self._providers.get(name)
        if client is None:
            raise LLMError(f"LLM provider {name!r} is not configured")
        return await client.generate(**kwargs)

    async def aclose(self) -> None:
        for client in self._providers.values():
            await client.aclose()
