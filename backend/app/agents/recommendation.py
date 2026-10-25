"""
RecommendationAgent — final BUY / HOLD / SELL from today's analyst results.

Weights come from each agent's @register_agent(recommendation_weight=...), so the
registry is the single source of truth. Runs after its dependencies (see registry).

Compliance: the reasoning is reviewed (app/domain/compliance.py) before it is
stored. Promissory language ("guaranteed", "risk-free") fails the review and the
reasoning is replaced with a neutral, score-based summary; the original text is
kept in compliance.original_reasoning for audit. Every result carries a disclaimer.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import (
    Agent,
    AnalysisResult,
    ComplianceFindingView,
    ComplianceView,
    quant_fallback,
)
from app.agents.formatting import memory_block
from app.agents.registry import register_agent, registry
from app.domain.compliance import DISCLAIMER, review_recommendation
from app.domain.scoring import (
    BUY_THRESHOLD,
    SELL_THRESHOLD,
    Action,
    ComplianceStatus,
    Contribution,
    WeightedScore,
    to_action,
)
from app.domain.scoring import weighted_score as compute_weighted_score
from app.schemas.signals import LLMSignal

# Must match the agents registered with a non-zero recommendation_weight
# (enforced by tests/unit/agents/test_catalog.py).
INPUT_AGENTS = (
    "financial_history",
    "valuation",
    "moat",
    "risk",
    "broad_analysis",
    "growth",
    "institutional",
    "earnings",
)
_MIN_AGENTS_FOR_CONVICTION = 4

logger = logging.getLogger(__name__)


class ContributionView(BaseModel):
    agent: str
    signal: str
    confidence: float
    weight: float
    contribution: float
    reasoning: str
    compliance_status: ComplianceStatus | None = None
    compliance_findings: list[ComplianceFindingView] = Field(default_factory=list)


class RecommendationResult(AnalysisResult):
    action: Action
    weighted_score: float
    agent_breakdown: list[ContributionView]
    agents_available: int
    agents_missing: list[str]
    risk_override_applied: bool
    compliance: ComplianceView
    disclaimer: str


@dataclass(frozen=True)
class RecommendationData:
    results: dict[str, dict[str, Any]]


@register_agent(
    "recommendation",
    description="Weighted BUY/HOLD/SELL across all analyst agents",
    depends_on=INPUT_AGENTS,
)
class RecommendationAgent(Agent[RecommendationData, RecommendationResult]):
    result_model = RecommendationResult

    async def fetch(self, symbol: str, run_date: date) -> RecommendationData:
        results = await self.ctx.results.get_for_date(symbol, run_date, list(INPUT_AGENTS))
        return RecommendationData(results=results)

    async def analyze(
        self, symbol: str, data: RecommendationData, memory: list[str]
    ) -> RecommendationResult:
        score = compute_weighted_score(data.results, registry.weights())
        available = len(data.results)

        if available < _MIN_AGENTS_FOR_CONVICTION:
            # Too little evidence for a call — HOLD without spending an LLM request
            judgement = LLMSignal(
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data: only {available}/{len(INPUT_AGENTS)} "
                "analysts reported",
            )
        else:
            judgement = await self.judge(
                _prompt(symbol, score, memory),
                fallback=quant_fallback(score.base_signal, score.base_confidence, "weighted score"),
                model=self.ctx.reasoning_model,
            )

        reasoning, compliance = _reviewed_reasoning(symbol, judgement, score)
        action = to_action(judgement.signal)
        return RecommendationResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=reasoning,
            action=action,
            weighted_score=score.score,
            agent_breakdown=[_contribution_view(c) for c in score.contributions],
            agents_available=available,
            agents_missing=list(score.missing),
            risk_override_applied=score.risk_override_applied,
            compliance=compliance,
            disclaimer=DISCLAIMER,
            summary=f"RECOMMENDATION: {action} ({judgement.confidence:.0f}%) "
            f"score={score.score:+.1f} — {reasoning}",
        )


def _contribution_view(c: Contribution) -> ContributionView:
    return ContributionView(
        **{
            **vars(c),
            "compliance_findings": [
                ComplianceFindingView(**vars(f)) for f in c.compliance_findings
            ],
        }
    )


def _reviewed_reasoning(
    symbol: str, judgement: LLMSignal, score: WeightedScore
) -> tuple[str, ComplianceView]:
    """Apply the compliance rules to the client-facing reasoning."""
    review = review_recommendation(judgement.reasoning, judgement.signal)
    findings = [ComplianceFindingView(**vars(f)) for f in review.findings]
    log_ctx = {"symbol": symbol, "findings": [vars(f) for f in review.findings]}

    if review.status == "fail":
        logger.warning(
            "Recommendation failed compliance review — reasoning replaced", extra=log_ctx
        )
        return _fallback_reasoning(score), ComplianceView(
            status="fail", findings=findings, original_reasoning=judgement.reasoning
        )
    if review.status == "flag":
        logger.info("Recommendation has compliance flags", extra=log_ctx)
    return judgement.reasoning, ComplianceView(status=review.status, findings=findings)


def _fallback_reasoning(score: WeightedScore) -> str:
    """Neutral, factual reasoning built from the score — used when the LLM text fails compliance."""
    top = sorted(
        (c for c in score.contributions if c.signal != "missing"),
        key=lambda c: abs(c.contribution),
        reverse=True,
    )[:3]
    drivers = ", ".join(f"{c.agent} {c.signal}" for c in top) or "no analyst signals"
    return (
        f"Weighted analyst score {score.score:+.1f}. Main drivers: {drivers}. "
        "Outcome is not certain; review the risks."
    )


def _prompt(symbol: str, s: WeightedScore, memory: list[str]) -> str:
    rows = "\n".join(
        f"{c.agent:<18} | {c.signal:<8} | {c.confidence:>3.0f}% | "
        f"{c.weight:>4.0f} | {c.contribution:+.2f}"
        for c in s.contributions
    )
    return f"""Symbol: {symbol}

Weighted score: {s.score:+.1f} (BUY > +{BUY_THRESHOLD:.0f}, SELL < {SELL_THRESHOLD:.0f})
Rule-based recommendation: {s.base_signal} ({s.base_confidence:.0f}%)
Risk override applied: {'yes' if s.risk_override_applied else 'no'}

Agent | Signal | Confidence | Weight | Contribution
{rows}

Missing analysts: {', '.join(s.missing) or 'none'}

Knowledge base context:
{memory_block(memory)}"""
