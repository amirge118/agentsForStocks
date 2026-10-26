"""
LLMRouter — what agents call. Sends each request to the provider its profile
names: "anthropic" (Claude, LLMClient), a free provider such as "gemini", "groq"
or "cerebras", "alt" (any OpenAI-compatible service), or "chain" (FallbackChain:
free providers first, Claude last). An unconfigured provider raises LLMError, so
the agent falls back to its own signal and the miss is counted like any other outage.

It is also the one place that answers questions about the configuration — which
providers exist, the chain's order, a model's price — for the API, the preflight
and the evals.
"""

from typing import Any

from app.llm.chain import FallbackChain
from app.llm.errors import LLMError
from app.llm.pricing import PRICES, Price
from app.llm.provider import ANTHROPIC, CHAIN, LLMProvider


class LLMRouter:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        default_provider: str = ANTHROPIC,
        chain: FallbackChain | None = None,
    ) -> None:
        self._providers = providers
        self._chain = chain or FallbackChain([], providers)
        self.default_provider = default_provider

    def configured(self, provider: str) -> bool:
        return provider == CHAIN or provider in self._providers

    def provider(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def providers(self) -> list[LLMProvider]:
        """Every configured provider (the chain is a route over them, not one of them)."""
        return list(self._providers.values())

    def chain_order(self) -> list[str]:
        """Provider names of the chain's steps, in the order they are tried."""
        return [step.provider for step in self._chain.steps]

    def default_model(self, provider: str | None = None) -> str | None:
        name = provider or self.default_provider
        if name == CHAIN:
            return self._chain.default_model or None
        client = self._providers.get(name)
        return client.default_model if client is not None else None

    def price(self, model: str) -> Price | None:
        """A model's price from whichever provider serves it, else the Claude price list."""
        for client in self._providers.values():
            price = client.price(model)
            if price is not None:
                return price
        return PRICES.get(model)

    async def generate(self, *, provider: str | None = None, **kwargs: Any) -> Any:
        name = provider or self.default_provider
        if name == CHAIN:
            return await self._chain.generate(**kwargs)
        client = self._providers.get(name)
        if client is None:
            raise LLMError(f"LLM provider {name!r} is not configured")
        return await client.generate(**kwargs)

    async def aclose(self) -> None:
        for client in self._providers.values():
            await client.aclose()
