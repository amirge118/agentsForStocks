"""
Run context — who is doing the work right now (pipeline run, agent run, agent,
symbol), carried in contextvars so every log line and LLM call can be attributed
without passing ids through every function.

asyncio copies the context into each task it creates, so a value bound before
`asyncio.gather` is visible inside every task, and each task's own bindings
stay private to it.

    with bind(pipeline_run_id=pid):
        with bind_run(run_id=rid, agent="moat", symbol="AAPL") as usage:
            ...                      # logs carry the ids; LLM calls add to `usage`
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# None rather than {} as the default: a mutable default would be one dict shared by every context
_fields: ContextVar[dict[str, str] | None] = ContextVar("run_context_fields", default=None)
_usage: ContextVar["RunUsage | None"] = ContextVar("run_usage", default=None)


@dataclass
class RunUsage:
    """LLM usage accumulated during one agent run (mutable, owned by that run)."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_fallbacks: int = 0
    # False once a call used a model with no known price, so the total is a lower bound
    cost_complete: bool = True


@contextmanager
def bind(**fields: str | None) -> Iterator[None]:
    """Add fields to the current context for the duration of the block."""
    token = _fields.set(
        {**(_fields.get() or {}), **{k: v for k, v in fields.items() if v is not None}}
    )
    try:
        yield
    finally:
        _fields.reset(token)


@contextmanager
def bind_run(**fields: str | None) -> Iterator[RunUsage]:
    """bind() plus a fresh RunUsage that LLM calls in the block add to."""
    usage = RunUsage()
    token = _usage.set(usage)
    try:
        with bind(**fields):
            yield usage
    finally:
        _usage.reset(token)


def current_fields() -> dict[str, str]:
    return dict(_fields.get() or {})


def current_usage() -> RunUsage | None:
    return _usage.get()


def note_fallback() -> None:
    """Count a judgement that fell back to the agent's own signal (LLM unavailable)."""
    usage = _usage.get()
    if usage is not None:
        usage.llm_fallbacks += 1
