"""
RecommendationAgent — final BUY / HOLD / SELL from today's analyst results.

Weights come from each agent's @register_agent(recommendation_weight=...), so the
registry is the single source of truth. Runs after its dependencies (see registry).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent, registry
from app.domain.scoring import BUY_THRESHOLD, SELL_THRESHOLD, Action, WeightedScore, to_action
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


class ContributionView(BaseModel):
    agent: str
    signal: str
    confidence: float
    weight: float
    contribution: float
    reasoning: str


class RecommendationResult(AnalysisResult):
    action: Action
    weighted_score: float
    agent_breakdown: list[ContributionView]
    agents_available: int
    agents_missing: list[str]
    risk_override_applied: bool


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

        action = to_action(judgement.signal)
        return RecommendationResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            action=action,
            weighted_score=score.score,
            agent_breakdown=[ContributionView(**vars(c)) for c in score.contributions],
            agents_available=available,
            agents_missing=list(score.missing),
            risk_override_applied=score.risk_override_applied,
            summary=f"RECOMMENDATION: {action} ({judgement.confidence:.0f}%) "
            f"score={score.score:+.1f} — {judgement.reasoning}",
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
