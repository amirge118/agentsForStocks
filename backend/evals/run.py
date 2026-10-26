"""
Run an eval. Without --yes it only prints the cost estimate (a live run calls
the real model and costs money). From backend/:

    python -m evals.run --suite scenarios --repeats 3                 # estimate only
    python -m evals.run --suite scenarios --repeats 3 --yes --label base
    python -m evals.run --agents valuation moat --label calibration --yes \\
        --profiles '{"*": {"skills": ["confidence_calibration"]}}'
    python -m evals.run --suite ledger --dataset evals/datasets/ledger.jsonl --judge --yes

Presets in evals/presets/: prompts_v2, haiku55, sonnet55_recommendation,
rule_based_quant, skills, cheap_alt_news, and the free tiers free_gemini,
free_groq, free_cerebras, free_chain — e.g. --profiles @evals/presets/haiku55.json.
A free tier costs nothing but has a daily request limit, shown with the estimate.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.container import build_llm_router
from app.core.config import Settings, settings
from app.core.logging import configure_logging
from app.llm.profiles import ProfileBook
from app.llm.recording import NullRecorder
from evals import cases as eval_cases
from evals import report
from evals.harness import Estimate, EvalConfig, estimate, grade, judge_faithfulness, run_case


def build_config(args: argparse.Namespace, s: Settings, llm: Any = None) -> EvalConfig:
    profiles = json.loads(s.agent_profiles) if s.agent_profiles else {}
    if args.profiles:
        profiles.update(_load_profiles(args.profiles))
    return EvalConfig(
        llm=llm
        or build_llm_router(s, NullRecorder()),  # evals never write to the production ledger
        profiles=ProfileBook(profiles),
        reasoning_model=s.llm_reasoning_model,
        repeats=args.repeats,
        judge_model=args.judge_model or s.llm_reasoning_model,
        judge_provider=args.judge_provider,
    )


def _load_profiles(value: str) -> dict[str, Any]:
    """Inline JSON, or @path to a JSON file (e.g. @evals/presets/haiku55.json)."""
    if value.startswith("@"):
        return dict(json.loads(Path(value[1:]).read_text(encoding="utf-8")))
    return dict(json.loads(value))


def load_cases(args: argparse.Namespace) -> list[eval_cases.EvalCase]:
    if args.suite == "ledger":
        return eval_cases.select(eval_cases.ledger_suite(Path(args.dataset)), args.agents)
    return eval_cases.select(eval_cases.scenario_suite(), args.agents)


def render_estimate(e: Estimate, cases: int, repeats: int) -> str:
    cost = (
        f"${e.cost_usd:.4f}"
        if e.cost_usd is not None
        else f"unknown (no price for {', '.join(e.unpriced_models)})"
    )
    return (
        f"{cases} cases × {repeats} repeats → ~{e.calls} model calls, "
        f"~{e.input_tokens:,} input + {e.output_tokens:,} output tokens, estimated cost {cost}"
    )


def quota_notes(config: EvalConfig, default_provider: str, calls: int) -> list[str]:
    """How much of each free tier's daily request limit the run would use."""
    llm = config.llm
    wanted = {default_provider} | {
        o["provider"] for o in config.profiles.overrides.values() if o.get("provider")
    }
    notes = []
    for name in sorted(wanted):
        client = llm.provider(name) if hasattr(llm, "provider") else None
        steps = getattr(client, "steps", None)
        if steps:  # a chain: the first step answers while it has quota
            name = steps[0].provider
            client = llm.provider(name)
        quota = getattr(client, "quota", None)
        if quota is not None and quota.limits.rpd:
            share = 100 * calls / quota.limits.rpd
            notes.append(
                f"{name} free tier: ~{calls} of {quota.limits.rpd} requests/day ({share:.0f}%)"
            )
    return notes


async def main(argv: list[str], llm: Any = None, out_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--suite", choices=["scenarios", "ledger"], default="scenarios")
    parser.add_argument("--dataset", default="evals/datasets/ledger.jsonl")
    parser.add_argument("--agents", nargs="+", default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--profiles", default="", help="agent-profile overrides: JSON, or @evals/presets/<x>.json"
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--judge", action="store_true", help="LLM-as-judge faithfulness check")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-provider", default=None)
    parser.add_argument(
        "--max-cost", type=float, default=5.0, help="refuse to run above this (USD)"
    )
    parser.add_argument("--yes", action="store_true", help="run against the real model")
    args = parser.parse_args(argv)

    config = build_config(args, settings, llm)
    selected = load_cases(args)
    if not selected:
        sys.stderr.write("No cases selected.\n")
        return 2
    est = await estimate(selected, config, judge=args.judge)
    sys.stdout.write(render_estimate(est, len(selected), args.repeats) + "\n")
    for note in quota_notes(config, settings.llm_provider, est.calls):
        sys.stdout.write(note + "\n")
    if est.cost_usd is not None and est.cost_usd > args.max_cost:
        sys.stdout.write(f"Estimated cost is above --max-cost {args.max_cost}; not running.\n")
        return 3
    if not args.yes:
        sys.stdout.write("Estimate only. Add --yes to run against the real model.\n")
        return 0

    graded = []
    for case in selected:
        runs = await run_case(case, config)
        if args.judge:
            await judge_faithfulness(runs, config)
        graded.append(grade(case, runs))
        sys.stdout.write(f"  {case.case_id:<36} {graded[-1]['modal_signal']}\n")
    run_config = {
        "suite": args.suite,
        "agents": args.agents,
        "repeats": args.repeats,
        "profiles": config.profiles.overrides,
        "default_model": settings.llm_default_model,
        "reasoning_model": settings.llm_reasoning_model,
        "provider": settings.llm_provider,
        "judge": args.judge,
    }
    path = report.write(args.label, run_config, graded, out_dir or report.REPORT_DIR)
    sys.stdout.write(path.with_suffix(".md").read_text(encoding="utf-8"))
    sys.stdout.write(f"\nReport: {path}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, "WARNING")
    sys.exit(asyncio.run(main(sys.argv[1:])))
