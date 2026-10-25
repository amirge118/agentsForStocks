"""Response/request models for /api/v1 — the contract the frontend is generated from."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.recommendation import ContributionView, RecommendationResult
from app.domain.scoring import Action
from app.domain.signals import SignalLabel


class AgentInfo(BaseModel):
    name: str
    description: str
    depends_on: list[str]
    recommendation_weight: float


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
            **result.model_dump(exclude={"agent_breakdown"}),
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
