"""
Metric instruments, created once from the global meter.

Until configure_telemetry() installs a MeterProvider the OpenTelemetry API hands
out no-op proxies, so recording is always safe — in tests, scripts and with
OTEL_ENABLED=false it simply does nothing.

In Prometheus (via the OTLP collector) the names become e.g. `llm_tokens_total`,
`agent_run_duration_milliseconds_bucket`.
"""

from opentelemetry import metrics

_meter = metrics.get_meter("agentsforstocks")

llm_calls = _meter.create_counter(
    "llm.calls", unit="{call}", description="Requests to the model, by agent, model and status"
)
llm_tokens = _meter.create_counter(
    "llm.tokens",
    unit="{token}",
    description="Tokens by agent, model and type (input, output, cache_read, cache_write)",
)
llm_cost = _meter.create_counter(
    "llm.cost", unit="USD", description="Model cost in US dollars, by agent and model"
)
llm_latency = _meter.create_histogram(
    "llm.latency", unit="ms", description="Model request latency, by agent and model"
)
agent_runs = _meter.create_counter(
    "agent.runs", unit="{run}", description="Agent runs by agent and status"
)
agent_run_duration = _meter.create_histogram(
    "agent.run.duration", unit="ms", description="Agent run wall time, by agent and status"
)
agent_fallbacks = _meter.create_counter(
    "agent.fallbacks",
    unit="{judgement}",
    description="Judgements that fell back to the agent's own signal (LLM unavailable)",
)
agent_data_gaps = _meter.create_counter(
    "agent.data_gaps", unit="{run}", description="Agent runs where some inputs came back empty"
)
agent_contract_violations = _meter.create_counter(
    "agent.contract_violations",
    unit="{violation}",
    description="Results that broke an agent's contract (app/agents/contracts.py)",
)
provider_requests = _meter.create_counter(
    "provider.requests",
    unit="{request}",
    description="Data provider lookups by domain and outcome (fetched, cache_hit)",
)
provider_duration = _meter.create_histogram(
    "provider.request.duration", unit="ms", description="Data provider request time, by domain"
)
fmp_calls = _meter.create_counter(
    "fmp.calls", unit="{call}", description="Calls counted against the FMP daily budget"
)
