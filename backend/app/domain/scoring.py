"""
Final recommendation scoring.

Each analyst signal becomes +1/0/-1, scaled by its confidence and its agent's
weight: BUY above +15, SELL below -15, HOLD otherwise. A high-confidence bearish
risk signal caps a bullish call at neutral.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.compliance import ComplianceFinding
from app.domain.signals import SignalLabel, direction

BUY_THRESHOLD = 15.0
SELL_THRESHOLD = -15.0
RISK_OVERRIDE_CONFIDENCE = 70.0
RISK_OVERRIDE_MAX_CONFIDENCE = 55.0

Action = Literal["BUY", "SELL", "HOLD"]
ComplianceStatus = Literal["pass", "flag", "fail"]
_COMPLIANCE_STATUSES: tuple[ComplianceStatus, ...] = ("pass", "flag", "fail")


@dataclass(frozen=True)
class Contribution:
    agent: str
    signal: str  # bullish | bearish | neutral | missing
    confidence: float
    weight: float
    contribution: float
    reasoning: str = ""
    # Outcome of the agent's compliance review; None for missing agents and
    # results stored before the review existed
    compliance_status: ComplianceStatus | None = None
    compliance_findings: tuple[ComplianceFinding, ...] = ()
    # The analyst's result needs a person's check (it fell back, see AnalysisResult)
    needs_review: bool = False


@dataclass(frozen=True)
class WeightedScore:
    score: float
    contributions: tuple[Contribution, ...]
    missing: tuple[str, ...]
    base_signal: SignalLabel
    base_confidence: float
    risk_override_applied: bool


def weighted_score(
    results: dict[str, dict[str, Any]],
    weights: dict[str, float],
    risk_agent: str = "risk",
    *,
    buy_threshold: float = BUY_THRESHOLD,
    sell_threshold: float = SELL_THRESHOLD,
) -> WeightedScore:
    contributions = []
    missing = []
    total = 0.0
    for agent, weight in weights.items():
        result = results.get(agent)
        if not result:
            missing.append(agent)
            contributions.append(Contribution(agent, "missing", 0.0, weight, 0.0))
            continue
        signal = str(result.get("signal", "neutral"))
        confidence = float(result.get("confidence") or 0)
        value = direction(signal) * confidence / 100 * weight
        total += value
        contributions.append(
            Contribution(
                agent,
                signal,
                confidence,
                weight,
                value,
                str(result.get("reasoning", "")),
                _compliance_status(result),
                _compliance_findings(result),
                bool(result.get("needs_review")),
            )
        )

    if total > buy_threshold:
        base: SignalLabel = "bullish"
    elif total < sell_threshold:
        base = "bearish"
    else:
        base = "neutral"
    confidence = min(abs(total) * 3, 90.0)

    base, confidence, override = risk_capped(base, confidence, results, risk_agent)

    return WeightedScore(
        score=total,
        contributions=tuple(contributions),
        missing=tuple(missing),
        base_signal=base,
        base_confidence=confidence,
        risk_override_applied=override,
    )


def risk_capped(
    signal: SignalLabel,
    confidence: float,
    results: dict[str, dict[str, Any]],
    risk_agent: str = "risk",
) -> tuple[SignalLabel, float, bool]:
    """
    A high-confidence bearish risk call caps the call at HOLD with at most
    RISK_OVERRIDE_MAX_CONFIDENCE: a bullish signal becomes neutral, and a neutral one
    keeps its signal but not a confidence above the cap (the model may answer HOLD
    itself, still too sure). A bearish call agrees with the risk analyst and is left
    alone. Returns (signal, confidence, capped) — capped when anything changed.
    Applied to the rule-based score and again to the final judgement, so the cap
    holds whatever the model answers.
    """
    risk = results.get(risk_agent) or {}
    override = (
        risk.get("signal") == "bearish"
        and float(risk.get("confidence") or 0) >= RISK_OVERRIDE_CONFIDENCE
    )
    if not override or signal == "bearish":
        return signal, confidence, False
    capped_confidence = min(confidence, RISK_OVERRIDE_MAX_CONFIDENCE)
    changed = signal != "neutral" or capped_confidence < confidence
    return "neutral", capped_confidence, changed


def to_action(signal: str) -> Action:
    if signal == "bullish":
        return "BUY"
    if signal == "bearish":
        return "SELL"
    return "HOLD"


def _compliance_status(result: dict[str, Any]) -> ComplianceStatus | None:
    compliance = result.get("compliance")
    status = compliance.get("status") if isinstance(compliance, dict) else None
    return status if status in _COMPLIANCE_STATUSES else None


def _compliance_findings(result: dict[str, Any]) -> tuple[ComplianceFinding, ...]:
    """Findings from the stored review; malformed entries are skipped."""
    compliance = result.get("compliance")
    raw = compliance.get("findings") if isinstance(compliance, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(
        ComplianceFinding(f["rule"], f["severity"], f.get("phrase") or "")
        for f in raw
        if isinstance(f, dict)
        and isinstance(f.get("rule"), str)
        and f.get("severity") in ("flag", "fail")
        and isinstance(f.get("phrase", ""), str)
    )
