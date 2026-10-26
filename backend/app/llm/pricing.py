"""
Token prices, USD per million tokens — used to put a cost on every LLM call.

Source: Anthropic's published API prices (verify at https://www.anthropic.com/pricing
when adding a model). Cache writes are the 5-minute TTL rate (1.25x input).
Claude Haiku 5.5 doubles its rates for prompts over 100K tokens; our prompts are
far below that, so the base rate is used.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float

    @classmethod
    def flat(cls, input: float, output: float) -> "Price":
        """A provider without cache pricing: cached tokens cost what input tokens cost."""
        return cls(input=input, output=output, cache_read=input, cache_write=input)


PRICES: dict[str, Price] = {
    "claude-haiku-4-5": Price(input=1.00, output=5.00, cache_read=0.10, cache_write=1.25),
    "claude-sonnet-4-6": Price(input=3.00, output=15.00, cache_read=0.30, cache_write=3.75),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01, cache_write=0.125),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20, cache_write=2.50),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20, cache_write=5.00),
}

_warned: set[str] = set()


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


def cost_usd(model: str, usage: TokenUsage, prices: dict[str, Price] | None = None) -> float | None:
    """Cost of one call, or None when the model has no known price."""
    price = (prices or PRICES).get(model)
    if price is None:
        if model not in _warned:
            _warned.add(model)
            logger.warning("No price known for model — cost not tracked", extra={"model": model})
        return None
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
