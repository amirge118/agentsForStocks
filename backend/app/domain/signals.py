"""Signal labels and conversions shared by every agent."""

from typing import Literal

SignalLabel = Literal["bullish", "bearish", "neutral"]

_DIRECTION: dict[str, float] = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def direction(label: str) -> float:
    """bullish → +1, bearish → -1, anything else → 0."""
    return _DIRECTION.get(label, 0.0)


def label_from_score(
    value: float, bullish_above: float = 0.2, bearish_below: float = -0.2
) -> SignalLabel:
    """Map a score (typically -1..+1) to a label using inclusive thresholds."""
    if value >= bullish_above:
        return "bullish"
    if value <= bearish_below:
        return "bearish"
    return "neutral"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
