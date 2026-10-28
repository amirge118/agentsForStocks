"""Institutional (13F) ownership metrics from FMP holder rows."""

from typing import Literal

# "unknown": no holder rows — no evidence of a flow either way, not a flat one
FlowDirection = Literal["accumulating", "distributing", "flat", "unknown"]


def net_share_change(holders: list[dict], top_n: int = 20) -> float | None:
    """Summed change of the top holders; None without holder rows."""
    if not holders:
        return None
    return float(sum(h.get("change") or 0 for h in holders[:top_n]))


def top5_concentration(holders: list[dict]) -> float | None:
    """Share of listed institutional holdings owned by the five largest holders (0-1)."""
    total = sum(h.get("shares") or 0 for h in holders)
    top5 = sum(h.get("shares") or 0 for h in holders[:5])
    return top5 / total if total > 0 else None


def flow_direction(net_change: float | None) -> FlowDirection:
    if net_change is None:
        return "unknown"
    if net_change > 0:
        return "accumulating"
    if net_change < 0:
        return "distributing"
    return "flat"
