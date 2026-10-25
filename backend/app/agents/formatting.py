"""Prompt formatting helpers shared by agents. Presentation only — no calculations."""

from collections.abc import Callable, Sequence


def billions(value: float | None) -> str:
    return "N/A" if value is None else f"${value / 1e9:.2f}B"


def pct(value: float | None) -> str:
    """Fraction → percent string (0.123 → 12.3%)."""
    return "N/A" if value is None else f"{value * 100:.1f}%"


def memory_block(memory: list[str]) -> str:
    return "\n".join(f"- {item}" for item in memory) if memory else "None"


def table(
    header: str,
    rows: Sequence[dict],
    columns: Sequence[tuple[str, Callable[[object], str]]],
    limit: int | None = None,
) -> str:
    """Pipe-separated table: first column is the row's year (date[:4])."""
    lines = [header]
    for row in rows[:limit]:
        cells = [str(row.get("date") or "?")[:4]]
        cells += [fmt(row.get(key)) for key, fmt in columns]
        lines.append(" | ".join(cells))
    return "\n".join(lines)
