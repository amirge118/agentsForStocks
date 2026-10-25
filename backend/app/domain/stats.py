"""Small statistics helpers over plain lists."""

import re
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


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def relevant_excerpt(
    text: str, keywords: Sequence[str], max_chars: int, lead_chars: int = 600
) -> str:
    """
    A shorter excerpt that keeps what matters: the opening (context) plus the
    sentences mentioning any keyword — each with the sentence that follows it —
    in document order, until max_chars. Gaps are marked with " … ".
    Falls back to the first max_chars when no keyword appears.
    """
    if len(text) <= max_chars:
        return text
    sentences = _SENTENCE_END.split(text)
    lowered = [s.lower() for s in sentences]
    words = [k.lower() for k in keywords]
    hits = [i for i, s in enumerate(lowered) if any(w in s for w in words)]
    if not hits:
        return text[:max_chars]

    chosen: set[int] = set()
    size = 0
    for i, sentence in enumerate(sentences):  # the opening, for context
        if size + len(sentence) > lead_chars:
            break
        chosen.add(i)
        size += len(sentence) + 1
    for i in hits:
        for j in (i, i + 1):
            if j < len(sentences) and j not in chosen and size + len(sentences[j]) <= max_chars:
                chosen.add(j)
                size += len(sentences[j]) + 1
    parts: list[str] = []
    previous = -1
    for i in sorted(chosen):
        if parts and i != previous + 1:
            parts.append("…")
        parts.append(sentences[i])
        previous = i
    return " ".join(parts)
