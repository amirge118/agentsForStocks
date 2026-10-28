"""
RecommendationAgent — final BUY / HOLD / SELL from today's analyst results.

Weights come from each agent's @register_agent(recommendation_weight=...), so the
registry is the single source of truth. Runs after its dependencies (see registry).

Compliance: the reasoning is reviewed (app/domain/compliance.py) before it is
stored. Promissory language ("guaranteed", "risk-free") fails the review and the
reasoning is replaced with a neutral, score-based summary; the original text is
kept in compliance.original_reasoning for audit. Every result carries a disclaimer.

Track record: the prompt also shows how this system's past recommendations on the
symbol turned out (20 trading days vs the benchmark) and the lessons the outcome
review drew from them — only outcomes known before the run date, so a rerun of a
past date never sees the future.
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
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent, registry
from app.domain.compliance import DISCLAIMER, review_recommendation
from app.domain.outcomes import REVIEW_HORIZON, TrackRecord
from app.domain.scoring import (
    BUY_THRESHOLD,
    SELL_THRESHOLD,
    Action,
    ComplianceStatus,
    Contribution,
    WeightedScore,
    risk_capped,
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
# Track record in the prompt: settled calls counted, lessons quoted
TRACK_CALLS = 20
LESSONS_SAME_SYMBOL = 3
LESSONS_OTHER_SYMBOLS = 2

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
    needs_review: bool = False


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
    # Not a missing input when empty: a symbol without settled calls is just new
    track_record: TrackRecord


@register_agent(
    "recommendation",
    description="Weighted BUY/HOLD/SELL across all analyst agents",
    # outcome_review first, so today's lessons are in the track record
    depends_on=(*INPUT_AGENTS, "outcome_review"),
    company_only=True,
)
class RecommendationAgent(Agent[RecommendationData, RecommendationResult]):
    result_model = RecommendationResult

    async def fetch(self, symbol: str, run_date: date) -> RecommendationData:
        results = await self.ctx.results.get_for_date(symbol, run_date, list(INPUT_AGENTS))
        outcomes = self.ctx.outcomes
        calls = await outcomes.settled_calls(
            symbol, agent=self.name, horizon=REVIEW_HORIZON, before=run_date, limit=TRACK_CALLS
        )
        lessons = await outcomes.lessons(
            until=run_date, symbol=symbol, limit=LESSONS_SAME_SYMBOL
        ) + await outcomes.lessons(
            until=run_date, exclude_symbol=symbol, limit=LESSONS_OTHER_SYMBOLS
        )
        benchmark = calls[0].benchmark if calls else "the benchmark"
        return RecommendationData(
            results=results,
            track_record=TrackRecord(REVIEW_HORIZON, benchmark, tuple(calls), tuple(lessons)),
        )

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
                _prompt(symbol, score, data.track_record, memory),
                fallback=quant_fallback(score.base_signal, score.base_confidence, "weighted score"),
                model=self.ctx.reasoning_model,
            )

        judgement, capped = _apply_risk_cap(judgement, data.results)
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
            risk_override_applied=score.risk_override_applied or capped,
            compliance=compliance,
            disclaimer=DISCLAIMER,
            summary=f"RECOMMENDATION: {action} ({judgement.confidence:.0f}%) "
            f"score={score.score:+.1f} — {reasoning}",
            needs_review=_review_reasons(score, available),
        )


def _review_reasons(score: WeightedScore, available: int) -> list[str]:
    """
    Why this call should be checked before it is trusted: a HOLD for lack of
    analysts is not a view on the stock, and an analyst's fallback is not a judgement.
    """
    reasons = []
    if available < _MIN_AGENTS_FOR_CONVICTION:
        reasons.append(f"only {available}/{len(INPUT_AGENTS)} analysts reported")
    fell_back = [c.agent for c in score.contributions if c.needs_review and c.weight > 0]
    if fell_back:
        reasons.append(f"analysts needing review: {', '.join(fell_back)}")
    return reasons


def _contribution_view(c: Contribution) -> ContributionView:
    return ContributionView(
        **{
            **vars(c),
            "compliance_findings": [
                ComplianceFindingView(**vars(f)) for f in c.compliance_findings
            ],
        }
    )


def _apply_risk_cap(
    judgement: LLMSignal, results: dict[str, dict[str, Any]]
) -> tuple[LLMSignal, bool]:
    """
    Enforce the risk override on the final call too: the prompt asks the model to
    respect it, this guarantees it. Returns the (possibly capped) judgement.
    """
    signal, confidence, capped = risk_capped(judgement.signal, judgement.confidence, results)
    if not capped:
        return judgement, False
    what = "Capped at HOLD" if judgement.signal == "bullish" else "Confidence capped"
    logger.info(
        "Recommendation capped by the risk override",
        extra={"from_signal": judgement.signal, "from_confidence": judgement.confidence},
    )
    return (
        LLMSignal(
            signal=signal,
            confidence=confidence,
            reasoning=f"{judgement.reasoning} {what}: the risk analyst is bearish "
            "with high confidence.",
        ),
        True,
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


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _track_record_block(symbol: str, track: TrackRecord) -> str:
    if not track.calls and not track.lessons:
        return "Track record: no settled recommendations yet."
    lines = [
        f"Track record of this system's recommendations for {symbol} "
        f"({track.horizon} trading days later, vs {track.benchmark}):"
    ]
    if track.calls:
        n = len(track.calls)
        captured = track.mean_captured_alpha or 0.0
        lines.append(
            f"{_count(n, 'settled call')}, {track.hits} right ({100 * track.hits / n:.0f}%), "
            f"mean alpha captured {captured * 100:+.1f}%"
        )
    else:
        lines.append("No settled calls for this symbol yet.")
    if track.lessons:
        lines.append("Lessons from past calls:")
        lines += [
            f"- {lesson.symbol} {lesson.decision_date} {lesson.signal}, "
            f"alpha {lesson.alpha * 100:+.1f}%: {lesson.text}"
            for lesson in track.lessons
        ]
    return "\n".join(lines)


def _prompt(symbol: str, s: WeightedScore, track: TrackRecord, memory: list[str]) -> str:
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

{_track_record_block(symbol, track)}

{knowledge_block(memory)}"""
