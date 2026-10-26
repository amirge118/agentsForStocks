"""
The provider contract: what every model client (Claude, an OpenAI-compatible
service) offers the router, the fallback chain, the preflight and the API —
so none of them needs to know which concrete client it is talking to.
"""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.llm.mcp import McpServer
from app.llm.pricing import Price
from app.llm.quota import ProviderQuota

T = TypeVar("T", bound=BaseModel)

# Provider names as they appear in LLM_PROVIDER, LLM_CHAIN and agent profiles
ANTHROPIC = "anthropic"
ALT = "alt"
CHAIN = "chain"


class LLMProvider(Protocol):
    name: str
    default_model: str
    # "native" (Claude's structured outputs), "json_schema" or "json_object"
    structured_mode: str
    # Free-tier limits, or None for a paid provider without client-side limits
    quota: ProviderQuota | None

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

    def price(self, model: str) -> Price | None:
        """USD per million tokens for one of this provider's models (None = unknown)."""
        ...

    async def aclose(self) -> None: ...
