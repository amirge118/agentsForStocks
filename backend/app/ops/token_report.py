"""Token and cost report from the llm_calls ledger (`python -m scripts.token_report`)."""

from app.repositories.llm_calls import UsageRow


def render_usage(rows: list[UsageRow], group_by: str, days: int) -> str:
    if not rows:
        return f"No LLM calls in the last {days} days."
    header = (
        f"{group_by:<28} {'calls':>6} {'errors':>6} {'input':>10} {'output':>9} "
        f"{'cache rd':>9} {'cost $':>9} {'avg ms':>7}"
    )
    lines = [f"LLM usage — last {days} days, by {group_by}", "", header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.key[:28]:<28} {r.calls:>6} {r.errors:>6} {r.input_tokens:>10,} "
            f"{r.output_tokens:>9,} {r.cache_read_tokens:>9,} {r.cost_usd:>9.4f} "
            f"{r.avg_latency_ms:>7.0f}"
        )
    lines.append("-" * len(header))
    lines.append(
        f"{'total':<28} {sum(r.calls for r in rows):>6} {sum(r.errors for r in rows):>6} "
        f"{sum(r.input_tokens for r in rows):>10,} {sum(r.output_tokens for r in rows):>9,} "
        f"{sum(r.cache_read_tokens for r in rows):>9,} {sum(r.cost_usd for r in rows):>9.4f}"
    )
    return "\n".join(lines)
