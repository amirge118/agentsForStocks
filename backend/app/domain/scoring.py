"""
Final recommendation scoring.

Each analyst signal becomes +1/0/-1, scaled by its confidence and its agent's
weight: BUY above +15, SELL below -15, HOLD otherwise. A high-confidence bearish
risk signal caps a bullish call at neutral.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.signals import SignalLabel, direction

BUY_THRESHOLD = 15.0
SELL_THRESHOLD = -15.0
RISK_OVERRIDE_CONFIDENCE = 70.0
RISK_OVERRIDE_MAX_CONFIDENCE = 55.0

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class Contribution:
    agent: str
    signal: str  # bullish | bearish | neutral | missing
    confidence: float
    weight: float
    contribution: float
    reasoning: str = ""


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
            Contribution(agent, signal, confidence, weight, value, str(result.get("reasoning", "")))
        )

    if total > BUY_THRESHOLD:
        base: SignalLabel = "bullish"
    elif total < SELL_THRESHOLD:
        base = "bearish"
    else:
        base = "neutral"
    confidence = min(abs(total) * 3, 90.0)

    risk = results.get(risk_agent) or {}
    override = (
        base == "bullish"
        and risk.get("signal") == "bearish"
        and float(risk.get("confidence") or 0) >= RISK_OVERRIDE_CONFIDENCE
    )
    if override:
        base, confidence = "neutral", min(confidence, RISK_OVERRIDE_MAX_CONFIDENCE)

    return WeightedScore(
        score=total,
        contributions=tuple(contributions),
        missing=tuple(missing),
        base_signal=base,
        base_confidence=confidence,
        risk_override_applied=override,
    )


def to_action(signal: str) -> Action:
    if signal == "bullish":
        return "BUY"
    if signal == "bearish":
        return "SELL"
    return "HOLD"
