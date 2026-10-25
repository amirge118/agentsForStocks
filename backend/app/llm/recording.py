"""
LLM call records — one per request to the model, success or failure, with the
tokens, cost, latency and (optionally) the exact prompt and reply.

LLMClient builds the record; an LLMCallRecorder stores it. Recording is
best-effort: a recorder failure is logged and never fails the agent run.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.pricing import TokenUsage
from app.models.llm_call import LLMCall
from app.repositories.llm_calls import LLMCallRepository

logger = logging.getLogger(__name__)

CallStatus = Literal["ok", "error"]


def prompt_version(system: str) -> str:
    """Short, stable id of a system prompt — changes whenever its text changes."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class LLMCallRecord:
    call_id: str
    created_at: datetime
    model: str
    prompt_name: str | None
    prompt_version: str
    status: CallStatus
    latency_ms: int
    usage: TokenUsage
    cost_usd: float | None
    stop_reason: str | None = None
    error: str | None = None
    request_id: str | None = None
    pipeline_run_id: str | None = None
    run_id: str | None = None
    agent: str | None = None
    symbol: str | None = None
    # Exact text sent and received; None when content capture is off
    system_prompt: str | None = None
    prompt: str | None = None
    response: str | None = None


class LLMCallRecorder(Protocol):
    async def record(self, call: LLMCallRecord) -> None: ...


class NullRecorder:
    async def record(self, call: LLMCallRecord) -> None:
        return None


class DbLLMCallRecorder:
    """Stores each record in llm_calls, in its own short-lived session."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, call: LLMCallRecord) -> None:
        try:
            async with self._session_factory() as session:
                LLMCallRepository(session).add(to_model(call))
                await session.commit()
        except Exception as exc:
            logger.error(
                "Could not record LLM call", extra={"call_id": call.call_id, "error": str(exc)}
            )


def to_model(call: LLMCallRecord) -> LLMCall:
    return LLMCall(
        call_id=call.call_id,
        created_at=call.created_at,
        pipeline_run_id=call.pipeline_run_id,
        run_id=call.run_id,
        agent=call.agent,
        symbol=call.symbol,
        model=call.model,
        prompt_name=call.prompt_name,
        prompt_version=call.prompt_version,
        status=call.status,
        stop_reason=call.stop_reason,
        error=call.error,
        request_id=call.request_id,
        latency_ms=call.latency_ms,
        input_tokens=call.usage.input_tokens,
        output_tokens=call.usage.output_tokens,
        cache_read_tokens=call.usage.cache_read_tokens,
        cache_write_tokens=call.usage.cache_write_tokens,
        cost_usd=call.cost_usd,
        system_prompt=call.system_prompt,
        prompt=call.prompt,
        response=call.response,
    )
