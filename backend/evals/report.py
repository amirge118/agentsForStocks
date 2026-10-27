"""Eval reports: a JSON file for machines and a Markdown summary for people."""

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).parent / "reports"


def summarize(graded: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str, rows: list[dict[str, Any]], digits: int = 3) -> float | None:
        # .get: reports written before a metric existed don't have its key
        values = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.fmean(values), digits) if values else None

    costs = [r["cost_usd"] for r in graded]
    per_agent: dict[str, dict[str, Any]] = {}
    for agent in sorted({r["agent"] for r in graded}):
        rows = [r for r in graded if r["agent"] == agent]
        per_agent[agent] = {
            "cases": len(rows),
            "label_accuracy": mean("label_accuracy", rows),
            "stability": mean("stability", rows),
            "fallback_rate": mean("fallback_rate", rows),
            "violation_rate": mean("violation_rate", rows),
            "faithfulness": mean("faithfulness", rows),
            "outcome_hit_rate": mean("outcome_hit_rate", rows),
            "alpha_captured": mean("alpha_captured", rows, 5),
            "avg_input_tokens": mean("avg_input_tokens", rows),
            "avg_output_tokens": mean("avg_output_tokens", rows),
            "cost_usd": (
                None
                if None in [r["cost_usd"] for r in rows]
                else round(sum(r["cost_usd"] for r in rows), 6)
            ),
        }
    return {
        "cases": len(graded),
        "labelled_cases": sum(1 for r in graded if r["labelled"]),
        "label_accuracy": mean("label_accuracy", graded),
        "confidence_ok": mean("confidence_ok", graded),
        "stability": mean("stability", graded),
        "fallback_rate": mean("fallback_rate", graded),
        "violation_rate": mean("violation_rate", graded),
        "faithfulness": mean("faithfulness", graded),
        "outcome_cases": sum(1 for r in graded if r.get("outcome_alpha") is not None),
        "outcome_hit_rate": mean("outcome_hit_rate", graded),
        "alpha_captured": mean("alpha_captured", graded, 5),
        "errors": sum(r["errors"] for r in graded),
        "cost_usd": None if None in costs else round(sum(costs), 6),
        "per_agent": per_agent,
    }


def write(
    label: str, config: dict[str, Any], graded: list[dict[str, Any]], out_dir: Path = REPORT_DIR
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{label}.json"
    report = {
        "label": label,
        "created_at": stamp,
        "config": config,
        "summary": summarize(graded),
        "cases": graded,
    }
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return path


def _fmt(value: Any, pct: bool = False) -> str:
    if value is None:
        return "—"
    if pct:
        return f"{value * 100:.0f}%"
    if isinstance(value, float):
        return f"{value:,.4f}" if value < 1 else f"{value:,.0f}"
    return str(value)


def _alpha(value: Any) -> str:
    """A return as a signed percentage, two decimals (alpha is often below 1%)."""
    return "—" if value is None else f"{value * 100:+.2f}%"


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    total_cost = "unknown" if s["cost_usd"] is None else f"${s['cost_usd']:.4f}"
    lines = [
        f"# Eval report — {report['label']} ({report['created_at']})",
        "",
        f"Config: `{json.dumps(report['config'], default=str)}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases (labelled) | {s['cases']} ({s['labelled_cases']}) |",
        f"| Label accuracy | {_fmt(s['label_accuracy'], True)} |",
        f"| Confidence within limit | {_fmt(s['confidence_ok'], True)} |",
        f"| Stability (same signal across repeats) | {_fmt(s['stability'], True)} |",
        f"| Faithfulness (judge) | {_fmt(s['faithfulness'], True)} |",
        f"| Fallback rate | {_fmt(s['fallback_rate'], True)} |",
        f"| Contract violation rate | {_fmt(s['violation_rate'], True)} |",
        f"| Errors | {s['errors']} |",
        f"| Cost | {total_cost} |",
    ]
    if s.get("outcome_cases"):
        lines += [
            f"| Outcome cases | {s['outcome_cases']} |",
            f"| Outcome hit rate (vs realised alpha) | {_fmt(s['outcome_hit_rate'], True)} |",
            f"| Mean alpha captured per call | {_alpha(s['alpha_captured'])} |",
        ]
    lines += [
        "",
        "## Per agent",
        "",
        "| Agent | Cases | Accuracy | Stability | Faithful | Violations "
        "| Avg in | Avg out | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for agent, a in s["per_agent"].items():
        cost = "$" + format(a["cost_usd"], ".4f") if a["cost_usd"] is not None else "—"
        lines.append(
            f"| {agent} | {a['cases']} | {_fmt(a['label_accuracy'], True)} | "
            f"{_fmt(a['stability'], True)} | {_fmt(a['faithfulness'], True)} | "
            f"{_fmt(a['violation_rate'], True)} | {_fmt(a['avg_input_tokens'])} | "
            f"{_fmt(a['avg_output_tokens'])} | {cost} |"
        )
    misses = [
        c for c in report["cases"] if c["label_accuracy"] is not None and c["label_accuracy"] < 1
    ]
    if misses:
        lines += [
            "",
            "## Missed labels",
            "",
            "| Case | Expected | Got | Accuracy |",
            "|---|---|---|---:|",
        ]
        for c in misses:
            lines.append(
                f"| {c['case_id']} | {', '.join(c['expected'])} | {c['modal_signal']} | "
                f"{_fmt(c['label_accuracy'], True)} |"
            )
    return "\n".join(lines) + "\n"


def compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Markdown table of the metrics that matter, A → B, per agent and overall."""

    def cell(x: Any, y: Any, pct: bool = True) -> str:
        if x is None or y is None:
            return f"{_fmt(x, pct)} → {_fmt(y, pct)}"
        delta = (y - x) * (100 if pct else 1)
        sign = "+" if delta >= 0 else ""
        unit = " pp" if pct else ""
        return f"{_fmt(x, pct)} → {_fmt(y, pct)} ({sign}{delta:.1f}{unit})"

    sa, sb = a["summary"], b["summary"]
    lines = [
        f"# {a['label']} → {b['label']}",
        "",
        "| Metric | Change |",
        "|---|---|",
        f"| Label accuracy | {cell(sa['label_accuracy'], sb['label_accuracy'])} |",
        f"| Stability | {cell(sa['stability'], sb['stability'])} |",
        f"| Faithfulness | {cell(sa['faithfulness'], sb['faithfulness'])} |",
        f"| Fallback rate | {cell(sa['fallback_rate'], sb['fallback_rate'])} |",
        f"| Violation rate | {cell(sa['violation_rate'], sb['violation_rate'])} |",
        f"| Cost (USD) | {cell(sa['cost_usd'], sb['cost_usd'], pct=False)} |",
    ]
    if sa.get("outcome_cases") or sb.get("outcome_cases"):
        lines += [
            "| Outcome hit rate | "
            f"{cell(sa.get('outcome_hit_rate'), sb.get('outcome_hit_rate'))} |",
            "| Alpha captured per call | "
            f"{_alpha(sa.get('alpha_captured'))} → {_alpha(sb.get('alpha_captured'))} |",
        ]
    lines += [
        "",
        "| Agent | Accuracy | Stability | Avg input tokens | Cost |",
        "|---|---|---|---|---|",
    ]
    for agent in sorted(set(sa["per_agent"]) | set(sb["per_agent"])):
        x, y = sa["per_agent"].get(agent, {}), sb["per_agent"].get(agent, {})
        lines.append(
            f"| {agent} | {cell(x.get('label_accuracy'), y.get('label_accuracy'))} | "
            f"{cell(x.get('stability'), y.get('stability'))} | "
            f"{cell(x.get('avg_input_tokens'), y.get('avg_input_tokens'), pct=False)} | "
            f"{cell(x.get('cost_usd'), y.get('cost_usd'), pct=False)} |"
        )
    return "\n".join(lines) + "\n"
