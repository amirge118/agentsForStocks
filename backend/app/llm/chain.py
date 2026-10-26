"""
FallbackChain — free first, paid last. Tries each step's provider in order and
returns the first valid structured reply:

    LLM_CHAIN=gemini,groq,cerebras,anthropic:claude-haiku-5-5

A step is `provider` or `provider:model`. A step moves on to the next when its
provider is not configured, its free-tier quota has no room (nothing is sent),
or the call fails in any way an LLMError covers: 429, 5xx, timeout, a reply that
doesn't match the schema, a reply cut off at max_tokens. Every attempt that was
sent is in the llm_calls ledger. When every step fails the chain raises
LLMError, and the agent falls back to its own rule-based signal as it does for
any outage. A caller bug (ValueError) is raised at once.

Model choice: a step's own model wins. A model passed by the caller (an agent's
profile or its reasoning-model hint) names a Claude model, so it is only used
by an `anthropic` step that names no model. Calls with MCP servers only go to
Anthropic steps — the other providers don't support them.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.llm.client import LLMError
from app.llm.mcp import McpServer
from app.llm.openai_compat import QuotaExhaustedError
from app.observability import metrics

logger = logging.getLogger(__name__)

CHAIN = "chain"
_ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ChainStep:
    provider: str
    model: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.model else self.provider


def parse_chain(spec: str) -> list[ChainStep]:
    steps = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        provider, _, model = part.partition(":")
        steps.append(ChainStep(provider.strip(), model.strip() or None))
    return steps


class FallbackChain:
    def __init__(self, steps: Sequence[ChainStep], providers: Mapping[str, Any]) -> None:
        # Only steps whose provider exists; the rest are skipped once, here
        self.steps = [s for s in steps if s.provider in providers and s.provider != CHAIN]
        self._providers = providers
        skipped = [s.label for s in steps if s not in self.steps]
        if skipped:
            logger.debug("LLM chain steps without a configured provider", extra={"steps": skipped})

    @property
    def default_model(self) -> str:
        """The model of the first step — what answers when the chain is healthy."""
        if not self.steps:
            return ""
        first = self.steps[0]
        return first.model or self._providers[first.provider].default_model

    async def generate(
        self,
        *,
        model: str | None = None,
        mcp_servers: Sequence[McpServer] | None = None,
        **kwargs: Any,
    ) -> Any:
        failures: list[str] = []
        for i, step in enumerate(self.steps):
            if mcp_servers and step.provider != _ANTHROPIC:
                continue
            chosen = step.model or (model if step.provider == _ANTHROPIC else None)
            try:
                return await self._providers[step.provider].generate(
                    model=chosen, mcp_servers=mcp_servers, **kwargs
                )
            except LLMError as exc:
                reason = "quota" if isinstance(exc, QuotaExhaustedError) else "error"
                failures.append(f"{step.label}: {exc}")
                nxt = self.steps[i + 1].provider if i + 1 < len(self.steps) else "(none)"
                metrics.llm_chain_fallthrough.add(
                    1, {"from": step.provider, "to": nxt, "reason": reason}
                )
                logger.info(
                    "LLM chain step failed, trying the next",
                    extra={"step": step.label, "next": nxt, "reason": reason, "error": str(exc)},
                )
        if not failures:
            raise LLMError("no provider in the LLM chain can serve this call")
        raise LLMError("every provider in the LLM chain failed — " + "; ".join(failures))

    async def aclose(self) -> None:
        """The router closes the underlying providers."""
