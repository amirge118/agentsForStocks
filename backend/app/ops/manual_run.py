"""One-off pipeline run from the command line (`python -m scripts.run_pipeline`)."""

from app.agents.runner import RunOutcome
from app.pipeline.orchestrator import PipelineReport


def render_report(report: PipelineReport) -> str:
    lines = [
        f"Pipeline {report.pipeline_run_id} for {report.run_date}: "
        + ", ".join(f"{n} {s}" for s, n in sorted(report.counts.items())),
        "",
    ]
    for outcome in sorted(report.outcomes, key=lambda o: (o.symbol, o.agent)):
        lines.append(_line(outcome))
    u = report.usage
    lines += [
        "",
        f"LLM: {u['llm_calls']} calls, {u['input_tokens']:,} input + "
        f"{u['output_tokens']:,} output tokens, ${u['cost_usd']:.4f}, "
        f"{u['llm_fallbacks']} fallbacks",
    ]
    return "\n".join(lines)


def _line(o: RunOutcome) -> str:
    head = f"{o.symbol:<6} {o.agent:<18} {o.status:<9}"
    if o.status == "failed":
        return f"{head} {o.error}"
    if o.result is None:
        return head
    extra = f" {o.result.action}" if hasattr(o.result, "action") else ""
    verdict = f"{o.result.signal:<8} {o.result.confidence:>3.0f}%{extra}"
    tokens = ""
    if o.usage is not None and o.usage.llm_calls:
        tokens = f" [{o.usage.input_tokens}+{o.usage.output_tokens} tok]"
    return f"{head} {verdict}{tokens}  {o.result.reasoning[:80]}"
