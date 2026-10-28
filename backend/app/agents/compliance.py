"""
Compliance gate for every agent result — applied by AgentRunner before a result
is stored or remembered, so no analyst's reasoning reaches the API, the
recommendation breakdown or the knowledge base without being reviewed.

  pass / flag → reasoning kept; the review is attached as result.compliance
  fail        → reasoning (and the summary built from it) replaced with a
                neutral notice; the original is kept in
                compliance.original_reasoning for audit

Agents that run their own, stricter review (RecommendationAgent) set
result.compliance themselves and are left untouched.
"""

import logging

from app.agents.base import AnalysisResult, ComplianceFindingView, ComplianceView
from app.domain.compliance import review_text

logger = logging.getLogger(__name__)


def apply_compliance(agent: str, symbol: str, result: AnalysisResult) -> AnalysisResult:
    if result.compliance is not None:
        return result

    review = review_text(result.reasoning, result.signal, require_risk_discussion=False)
    findings = [ComplianceFindingView(**vars(f)) for f in review.findings]
    log_ctx = {"agent": agent, "symbol": symbol, "findings": [vars(f) for f in review.findings]}

    if review.status != "fail":
        if review.status == "flag":
            logger.info("Agent reasoning has compliance flags", extra=log_ctx)
        return result.model_copy(
            update={"compliance": ComplianceView(status=review.status, findings=findings)}
        )

    logger.warning("Agent reasoning failed compliance review — reasoning replaced", extra=log_ctx)
    replacement = withheld_reasoning(result.signal, result.confidence)
    summary = result.summary.replace(result.reasoning, replacement)
    if review_text(summary, result.signal, require_risk_discussion=False).status == "fail":
        # The offending text reached the summary some other way — rebuild it
        summary = f"{agent}: {result.signal} ({result.confidence:.0f}%) — {replacement}"
    return result.model_copy(
        update={
            "reasoning": replacement,
            "summary": summary,
            "compliance": ComplianceView(
                status="fail", findings=findings, original_reasoning=result.reasoning
            ),
        }
    )


def withheld_reasoning(signal: str, confidence: float) -> str:
    return (
        f"Analyst commentary withheld after compliance review. "
        f"Signal: {signal} at {confidence:.0f}% confidence."
    )


def review_stored(agent: str, symbol: str, stored: dict) -> dict | None:
    """
    The compliance review for a result stored before the gate existed: the stored
    payload with `compliance` added (and the reasoning replaced on a fail), or None
    when it was already reviewed.
    """
    if stored.get("compliance") is not None:
        return None
    base = AnalysisResult(
        signal=stored.get("signal", "neutral"),
        confidence=float(stored.get("confidence") or 0.0),
        reasoning=str(stored.get("reasoning", "")),
        summary=str(stored.get("summary", "")),
    )
    reviewed = apply_compliance(agent, symbol, base)
    compliance = reviewed.compliance.model_dump(mode="json") if reviewed.compliance else None
    return {
        **stored,
        "reasoning": reviewed.reasoning,
        "summary": reviewed.summary,
        "compliance": compliance,
    }
