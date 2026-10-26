"""
CallTracker — the bookkeeping every LLM client does for one request: timing,
token usage, cost, and the final LLMCallRecord, which is logged, counted in
metrics, added to the current agent run's usage and stored in the ledger.

Shared by every provider client (Claude, OpenAI-compatible), so each call is
measured the same way whichever model answers it.
"""

import logging
import time
from uuid import uuid4

from app.core.clock import utcnow
from app.core.context import current_fields, current_usage
from app.llm.pricing import Price, TokenUsage, cost_usd
from app.llm.recording import CallStatus, LLMCallRecord, LLMCallRecorder, prompt_version
from app.observability import metrics

logger = logging.getLogger(__name__)


class CallTracker:
    def __init__(
        self,
        *,
        recorder: LLMCallRecorder,
        model: str,
        system: str,
        prompt: str,
        prompt_name: str | None,
        capture_content: bool,
        prices: dict[str, Price] | None = None,
        provider: str | None = None,
    ) -> None:
        self._recorder = recorder
        self._provider = provider
        self._model = model
        self._system = system
        self._prompt = prompt
        self._prompt_name = prompt_name
        self._capture = capture_content
        self._prices = prices
        self._started = time.perf_counter()
        self.usage = TokenUsage()
        self.stop_reason: str | None = None
        self.request_id: str | None = None
        self.response: str | None = None

    def observe(
        self,
        usage: TokenUsage,
        *,
        stop_reason: str | None,
        response: str,
        request_id: str | None = None,
    ) -> None:
        self.usage = usage
        self.stop_reason = stop_reason
        self.response = response
        self.request_id = request_id

    async def finish(
        self, status: CallStatus, *, error: str | None = None, request_id: str | None = None
    ) -> LLMCallRecord:
        fields = current_fields()
        record = LLMCallRecord(
            call_id=str(uuid4()),
            created_at=utcnow(),
            model=self._model,
            prompt_name=self._prompt_name,
            prompt_version=prompt_version(self._system),
            status=status,
            latency_ms=round((time.perf_counter() - self._started) * 1000),
            usage=self.usage,
            cost_usd=cost_usd(self._model, self.usage, self._prices),
            stop_reason=self.stop_reason,
            error=error,
            request_id=request_id or self.request_id,
            pipeline_run_id=fields.get("pipeline_run_id"),
            run_id=fields.get("run_id"),
            agent=fields.get("agent"),
            symbol=fields.get("symbol"),
            provider=self._provider,
            system_prompt=self._system if self._capture else None,
            prompt=self._prompt if self._capture else None,
            response=self.response if self._capture else None,
        )
        _log(record)
        _accumulate(record)
        _measure(record)
        await self._recorder.record(record)
        return record


def _log(record: LLMCallRecord) -> None:
    extra = {
        "call_id": record.call_id,
        "provider": record.provider,
        "model": record.model,
        "prompt_name": record.prompt_name,
        "prompt_version": record.prompt_version,
        "llm_status": record.status,
        "input_tokens": record.usage.input_tokens,
        "output_tokens": record.usage.output_tokens,
        "cache_read_tokens": record.usage.cache_read_tokens,
        "cache_write_tokens": record.usage.cache_write_tokens,
        "cost_usd": record.cost_usd,
        "latency_ms": record.latency_ms,
        "stop_reason": record.stop_reason,
    }
    if record.status == "ok":
        logger.info("LLM call completed", extra=extra)
    else:
        logger.warning("LLM call failed", extra={**extra, "error": record.error})


def _measure(record: LLMCallRecord) -> None:
    attrs = {"agent": record.agent or "(none)", "model": record.model}
    metrics.llm_calls.add(1, {**attrs, "status": record.status})
    metrics.llm_latency.record(record.latency_ms, attrs)
    for kind, count in (
        ("input", record.usage.input_tokens),
        ("output", record.usage.output_tokens),
        ("cache_read", record.usage.cache_read_tokens),
        ("cache_write", record.usage.cache_write_tokens),
    ):
        if count:
            metrics.llm_tokens.add(count, {**attrs, "type": kind})
    if record.cost_usd:
        metrics.llm_cost.add(record.cost_usd, attrs)


def _accumulate(record: LLMCallRecord) -> None:
    usage = current_usage()
    if usage is None:
        return
    usage.llm_calls += 1
    usage.input_tokens += record.usage.total_input
    usage.output_tokens += record.usage.output_tokens
    if record.cost_usd is None:
        usage.cost_complete = False
    else:
        usage.cost_usd += record.cost_usd
