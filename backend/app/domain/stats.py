"""Small statistics helpers over plain lists."""

from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def sample_variance(values: Sequence[float]) -> float:
    """Sample variance; 0 for fewer than two values."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return sum((v - m) ** 2 for v in values) / (len(values) - 1)


def cagr(rows: Sequence[dict], field: str) -> float:
    """
    Compound annual growth rate of `field` across yearly rows ordered most-recent first.
    0.0 when there are fewer than two values or either endpoint is non-positive.
    """
    values = [r[field] for r in rows if r.get(field) is not None]
    if len(values) < 2:
        return 0.0
    newest, oldest = values[0], values[-1]
    if oldest <= 0 or newest <= 0:
        return 0.0
    return (newest / oldest) ** (1 / (len(values) - 1)) - 1


def find_keywords(text: str, keywords: Sequence[str]) -> list[str]:
    """Keywords present in text (case-insensitive), in keyword order."""
    lowered = text.lower()
    return [kw for kw in keywords if kw in lowered]
