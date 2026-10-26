"""Errors every model provider raises — the agents only need to know these two."""


class LLMError(Exception):
    """The model could not produce a valid structured reply (outage, refusal, bad JSON, ...)."""


class QuotaExhaustedError(LLMError):
    """A free tier has no room for the request now (rate limit or daily quota)."""
