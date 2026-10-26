"""Response/request models for /api/v1 — the contract the frontend is generated from."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.recommendation import ComplianceView, ContributionView, RecommendationResult
from app.domain.scoring import Action
from app.domain.signals import SignalLabel
from app.repositories.llm_calls import GroupBy


class AgentProfileOut(BaseModel):
    """How the agent's main judgement is made (defaults + AGENT_PROFILES overrides)."""

    provider: str
    model: str | None = Field(description="None = the agent's own default (e.g. reasoning model)")
    skills: list[str]
    use_llm: bool


class AgentInfo(BaseModel):
    name: str
    description: str
    depends_on: list[str]
    recommendation_weight: float
    profile: AgentProfileOut


class AgentResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    symbol: str
    run_date: date
    run_id: str
    updated_at: datetime
    result: dict[str, Any] = Field(validation_alias="result_json")


class Recommendation(BaseModel):
    symbol: str
    run_date: date
    updated_at: datetime
    action: Action
    signal: SignalLabel
    confidence: float
    weighted_score: float
    reasoning: str
    summary: str
    agents_available: int
    agents_missing: list[str]
    risk_override_applied: bool
    compliance: ComplianceView
    disclaimer: str
    agent_breakdown: list[ContributionView]

    @classmethod
    def from_row(
        cls, symbol: str, run_date: date, updated_at: datetime, result_json: dict[str, Any]
    ) -> "Recommendation":
        result = RecommendationResult.model_validate(result_json)
        return cls(
            symbol=symbol,
            run_date=run_date,
            updated_at=updated_at,
            **result.model_dump(exclude={"agent_breakdown", "compliance"}),
            compliance=result.compliance,
            agent_breakdown=result.agent_breakdown,
        )


class SymbolOverview(BaseModel):
    symbol: str
    recommendation: Recommendation | None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    pipeline_run_id: str | None
    agent_type: str
    symbol: str
    run_date: date
    status: Literal["completed", "skipped", "failed"]
    error: str | None
    started_at: datetime
    finished_at: datetime
    fetch_ms: int | None
    analyze_ms: int | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    llm_fallbacks: int


class LLMCallOut(BaseModel):
    """One request to the model, with the exact text sent and received (when captured)."""

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    created_at: datetime
    pipeline_run_id: str | None
    run_id: str | None
    agent: str | None
    symbol: str | None
    provider: str | None = Field(description="Which provider answered; None before migration 0004")
    model: str
    prompt_name: str | None
    prompt_version: str
    status: Literal["ok", "error"]
    stop_reason: str | None
    error: str | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float | None
    system_prompt: str | None
    prompt: str | None
    response: str | None


class LLMUsageRow(BaseModel):
    """Token and cost totals for one group (agent, model, day or prompt version)."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    avg_latency_ms: float


class LLMUsageReport(BaseModel):
    since: datetime
    group_by: GroupBy
    rows: list[LLMUsageRow]
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class PipelineRunRequest(BaseModel):
    symbols: list[str] | None = Field(
        default=None, description="Defaults to the configured watchlist", max_length=50
    )
    agents: list[str] | None = Field(default=None, description="Defaults to every agent")
    force: bool = Field(default=False, description="Re-run agents that already ran today")


class PipelineRunAccepted(BaseModel):
    pipeline_run_id: str
    run_date: date
    symbols: list[str]
    agents: list[str]
    force: bool


class LLMProviderOut(BaseModel):
    """A configured model provider: its place in the fallback chain, limits and use today."""

    name: str
    model: str
    structured_mode: str | None = Field(description="None for Claude (native structured outputs)")
    chain_position: int | None = Field(description="1 = tried first; None = not in LLM_CHAIN")
    rpm: int | None
    tpm: int | None
    rpd: int | None
    tpd: int | None
    day_start: datetime = Field(description="When the provider's daily quota last reset")
    day_requests: int
    day_tokens: int
