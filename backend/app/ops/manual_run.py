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
    return "\n".join(lines)


def _line(o: RunOutcome) -> str:
    head = f"{o.symbol:<6} {o.agent:<18} {o.status:<9}"
    if o.status == "failed":
        return f"{head} {o.error}"
    if o.result is None:
        return head
    extra = f" {o.result.action}" if hasattr(o.result, "action") else ""
    verdict = f"{o.result.signal:<8} {o.result.confidence:>3.0f}%{extra}"
    return f"{head} {verdict}  {o.result.reasoning[:80]}"
