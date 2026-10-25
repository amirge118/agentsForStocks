"""
OpenTelemetry setup — traces, metrics and logs exported over OTLP/HTTP.

Off by default (OTEL_ENABLED=false): nothing is installed and every span or
metric in the code is a no-op. When enabled, the standard OTEL_* environment
variables configure the exporters (OTEL_EXPORTER_OTLP_ENDPOINT, headers, …), so
any OTLP backend works; `docker compose --profile observability` runs a local
Grafana (Tempo + Loki + Prometheus) at http://localhost:3001.

Instrumented automatically: FastAPI requests (except /health), outgoing httpx
requests (FMP, SEC) and SQLAlchemy queries. The Anthropic SDK emits its own
`gen_ai` spans for every Claude request (metadata only — the prompt text lives
in the llm_calls ledger). Pipeline, agent, fetch/analyze and yfinance spans are
created by the app itself.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.logging import ContextFilter, extra_fields, scrub

logger = logging.getLogger(__name__)


class _ScrubbingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(record.getMessage())


class OtlpLogHandler(LoggingHandler):
    """
    OTLP log handler with the same guarantees as the stdout handler: run context
    attached, sensitive fields redacted, secrets scrubbed from text, and values
    the OTLP data model can't carry (dates, objects) turned into strings.
    """

    def __init__(self, logger_provider: LoggerProvider) -> None:
        super().__init__(logger_provider=logger_provider)
        self.addFilter(ContextFilter())
        self.setFormatter(_ScrubbingFormatter())

    def _get_attributes(self, record: logging.LogRecord) -> tuple[dict[str, Any], str | None]:
        attributes, event_name = super()._get_attributes(record)
        cleaned = {k: _attribute(v) for k, v in extra_fields(record).items()}
        for key in ("exception.type", "exception.message", "exception.stacktrace"):
            if key in attributes:
                cleaned[key] = scrub(str(attributes[key]))
        return cleaned, event_name


def _attribute(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return scrub(value)
    return scrub(json.dumps(value, default=str))


@dataclass
class Exporters:
    """Where telemetry goes. Defaults to OTLP/HTTP; tests pass in-memory ones."""

    spans: SpanExporter | None = None
    metric_reader: MetricReader | None = None
    logs: LogRecordExporter | None = None


@dataclass
class Telemetry:
    enabled: bool
    _providers: list[Any] = field(default_factory=list)
    _log_handler: logging.Handler | None = None

    def force_flush(self) -> None:
        for provider in self._providers:
            provider.force_flush()

    def shutdown(self) -> None:
        """Flush and stop exporting. Safe to call when disabled."""
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
        for provider in self._providers:
            provider.shutdown()


def configure_telemetry(
    settings: Settings,
    *,
    service_name: str,
    app: Any | None = None,
    engine: AsyncEngine | None = None,
    exporters: Exporters | None = None,
    metric_interval_ms: int = 15_000,
) -> Telemetry:
    """
    Install tracer, meter and logger providers (once per process) and the
    automatic instrumentation. Returns a disabled Telemetry when OTEL_ENABLED=false.
    """
    if not settings.otel_enabled:
        return Telemetry(enabled=False)

    exporters = exporters or Exporters()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "agentsforstocks",
            "deployment.environment": settings.environment,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporters.spans or OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            exporters.metric_reader
            or PeriodicExportingMetricReader(
                OTLPMetricExporter(), export_interval_millis=metric_interval_ms
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(exporters.logs or OTLPLogExporter())
    )
    _logs.set_logger_provider(logger_provider)
    # Ships every record to the backend with the active trace and span ids
    log_handler = OtlpLogHandler(logger_provider=logger_provider)
    logging.getLogger().addHandler(log_handler)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    HTTPXClientInstrumentor().instrument()
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    logger.info("OpenTelemetry enabled", extra={"service": service_name})
    return Telemetry(
        enabled=True,
        _providers=[tracer_provider, meter_provider, logger_provider],
        _log_handler=log_handler,
    )
