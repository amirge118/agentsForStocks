"""
OpenTelemetry wiring, with in-memory exporters. The OTel API allows one global
provider per process, so telemetry is configured once for this module.
"""

import json
import logging
from collections.abc import Iterator
from datetime import date

import pytest
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.registry import AgentRegistry
from app.agents.runner import AgentRunner
from app.core.config import Settings
from app.core.context import current_usage
from app.knowledge.store import NullKnowledgeStore
from app.observability.telemetry import (
    Exporters,
    Telemetry,
    configure_telemetry,
)
from app.pipeline.orchestrator import PipelineOrchestrator
from tests.factories import FakeLLM, make_context

RUN_DATE = date(2026, 10, 23)


class _Telemetry:
    def __init__(self) -> None:
        self.spans = InMemorySpanExporter()
        self.metrics = InMemoryMetricReader()
        self.logs = InMemoryLogRecordExporter()
        self.telemetry: Telemetry | None = None


@pytest.fixture(scope="module")
def otel() -> Iterator[_Telemetry]:
    sink = _Telemetry()
    sink.telemetry = configure_telemetry(
        Settings(otel_enabled=True, environment="test"),
        service_name="agentsforstocks-test",
        exporters=Exporters(spans=sink.spans, metric_reader=sink.metrics, logs=sink.logs),
    )
    yield sink
    sink.telemetry.shutdown()
    HTTPXClientInstrumentor().uninstrument()


@pytest.fixture
def fresh(otel: _Telemetry) -> _Telemetry:
    otel.telemetry.force_flush()
    otel.spans.clear()
    otel.logs.clear()
    return otel


class _UsageLLM(FakeLLM):
    async def generate(self, **kwargs):
        usage = current_usage()
        if usage is not None:
            usage.llm_calls += 1
            usage.input_tokens += 1200
            usage.output_tokens += 80
        return await super().generate(**kwargs)


def _orchestrator(session_factory, *, failing: str | None = None) -> PipelineOrchestrator:
    reg = AgentRegistry()

    class _Agent(Agent[None, AnalysisResult]):
        result_model = AnalysisResult

        async def fetch(self, symbol: str, run_date: date) -> None:
            logging.getLogger("app.tests.agent").info("fetching")
            if self.name == failing:
                raise RuntimeError("provider down")

        async def analyze(self, symbol: str, data: None, memory: list[str]) -> AnalysisResult:
            j = await self.judge(
                "p", fallback=quant_fallback("neutral", 1, "q"), prompt_name="technicals"
            )
            return AnalysisResult(
                signal=j.signal, confidence=j.confidence, reasoning=j.reasoning, summary="s"
            )

    reg.register("alpha", description="a")(_Agent)
    reg.register("beta", description="b")(type("_Beta", (_Agent,), {}))
    ctx = make_context(llm=_UsageLLM())
    return PipelineOrchestrator(
        AgentRunner(session_factory, NullKnowledgeStore()),
        reg,
        build_agent=lambda name: reg.get(name).agent_cls(ctx),
    )


def _metric_points(reader: InMemoryMetricReader, name: str) -> list:
    data = reader.get_metrics_data()
    return [
        point
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


@pytest.mark.unit
def test_disabled_telemetry_installs_nothing() -> None:
    telemetry = configure_telemetry(Settings(otel_enabled=False), service_name="x")
    assert telemetry.enabled is False
    telemetry.force_flush()
    telemetry.shutdown()  # no-op


@pytest.mark.unit
async def test_pipeline_produces_a_span_tree(fresh: _Telemetry, concurrent_session_factory) -> None:
    report = await _orchestrator(concurrent_session_factory, failing="beta").run(
        ["AAPL"], run_date=RUN_DATE
    )
    fresh.telemetry.force_flush()
    spans = {s.name: s for s in fresh.spans.get_finished_spans()}

    pipeline = spans["pipeline.run"]
    assert pipeline.attributes["pipeline.run_id"] == report.pipeline_run_id
    assert pipeline.attributes["pipeline.llm_calls"] == 1
    symbol = spans["pipeline.symbol"]
    assert symbol.parent.span_id == pipeline.context.span_id
    runs = [s for s in fresh.spans.get_finished_spans() if s.name == "agent.run"]
    assert {r.attributes["agent"] for r in runs} == {"alpha", "beta"}
    assert all(r.parent.span_id == symbol.context.span_id for r in runs)
    failed = next(r for r in runs if r.attributes["agent"] == "beta")
    assert failed.status.status_code.name == "ERROR"
    ok = next(r for r in runs if r.attributes["agent"] == "alpha")
    assert ok.attributes["llm.input_tokens"] == 1200
    fetch = [s for s in fresh.spans.get_finished_spans() if s.name == "agent.fetch"]
    assert {f.parent.span_id for f in fetch} == {r.context.span_id for r in runs}
    # Every span of the run shares one trace
    assert len({s.context.trace_id for s in fresh.spans.get_finished_spans()}) == 1


@pytest.mark.unit
async def test_agent_metrics_are_recorded(fresh: _Telemetry, concurrent_session_factory) -> None:
    await _orchestrator(concurrent_session_factory, failing="beta").run(["MSFT"], run_date=RUN_DATE)
    runs = {
        (p.attributes["agent"], p.attributes["status"]): p.value
        for p in _metric_points(fresh.metrics, "agent.runs")
    }
    assert runs[("alpha", "completed")] >= 1 and runs[("beta", "failed")] >= 1
    durations = _metric_points(fresh.metrics, "agent.run.duration")
    assert sum(p.count for p in durations) >= 2


@pytest.mark.unit
async def test_logs_are_exported_with_trace_context_and_redaction(
    fresh: _Telemetry, concurrent_session_factory
) -> None:
    logging.getLogger().setLevel(logging.INFO)
    await _orchestrator(concurrent_session_factory).run(["NVDA"], run_date=RUN_DATE)
    logging.getLogger("app.tests").warning(
        "secret check apikey=abc123", extra={"api_key": "s3cret", "when": RUN_DATE, "n": [1, 2]}
    )
    fresh.telemetry.force_flush()
    records = [r.log_record for r in fresh.logs.get_finished_logs()]

    fetching = [r for r in records if r.body == "fetching"]
    assert fetching and all(r.trace_id for r in fetching)  # linked to the agent's trace
    assert fetching[0].attributes["symbol"] == "NVDA"
    assert "run_id" in fetching[0].attributes
    (secret,) = (r for r in records if str(r.body).startswith("secret check"))
    assert "abc123" not in secret.body
    assert secret.attributes["api_key"] == "***"
    assert secret.attributes["when"] == '"2026-10-23"'
    assert json.loads(secret.attributes["n"]) == [1, 2]


@pytest.mark.unit
async def test_llm_and_provider_metrics(fresh: _Telemetry) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.llm.client import LLMClient
    from app.providers.cache import TTLCache
    from app.providers.fmp import DailyCallBudget
    from app.providers.yfinance import YFinanceClient
    from app.schemas.signals import LLMSignal

    message = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="text", text='{"signal":"bullish","confidence":5,"reasoning":"r"}')
        ],
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=40,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    sdk = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))
    await LLMClient(sdk, "claude-haiku-4-5").generate(
        system="s", prompt="p", schema=LLMSignal, prompt_name="moat"
    )
    tokens = {p.attributes["type"]: p.value for p in _metric_points(fresh.metrics, "llm.tokens")}
    assert tokens["input"] >= 500 and tokens["output"] >= 40
    assert any(p.value > 0 for p in _metric_points(fresh.metrics, "llm.cost"))

    class _Limiter:
        async def acquire(self, domain: str) -> None:
            return None

    yf = YFinanceClient(
        _Limiter(),
        TTLCache(60),
        ticker_factory=lambda t: SimpleNamespace(info={"a": 1}),
    )
    await yf.get_info("AAPL")
    await yf.get_info("AAPL")  # cache hit
    outcomes = {
        p.attributes["outcome"]: p.value
        for p in _metric_points(fresh.metrics, "provider.requests")
        if p.attributes["domain"] == "yahoo"
    }
    assert outcomes["fetched"] >= 1 and outcomes["cache_hit"] >= 1
    fresh.telemetry.force_flush()
    assert any(s.name == "yfinance.info" for s in fresh.spans.get_finished_spans())

    DailyCallBudget(10).consume()
    assert sum(p.value for p in _metric_points(fresh.metrics, "fmp.calls")) >= 1
