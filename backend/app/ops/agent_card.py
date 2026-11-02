"""
Agent card — where one agent stands, and where to start improving it
(`python -m scripts.agent_card <agent>`; the loop is in docs/agent-improvement-loop.md).

Everything comes from what is already stored — agent_runs, agent_results,
llm_calls, decision_outcomes — so building a card calls no model and no data
provider. The hints are rules of thumb that point at the first thing to look at;
they never change anything.
"""

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry
from app.domain.outcomes import REVIEW_HORIZON, AgentTrack, agent_tracks
from app.llm.profiles import AgentProfile, ProfileBook
from app.repositories.agent_results import AgentResultRepository
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.decision_outcomes import DecisionOutcomeRepository
from app.repositories.llm_calls import LLMCallRepository, UsageRow

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "tests" / "snapshots" / "prompts"
# Rules of thumb behind the hints
GAP_SHARE = 0.30  # results with a data gap
FALLBACK_SHARE = 0.10  # runs that fell back to the rule-based signal
MIN_LABELLED_CASES = 2  # labelled eval cases before a prompt change can be judged
_MAX_RUNS = 1_000
_MAX_RESULTS = 500


@dataclass(frozen=True)
class EvalCoverage:
    cases: int
    labelled: int


@dataclass(frozen=True)
class RunStats:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    llm_fallbacks: int = 0
    avg_analyze_ms: float | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class LatestCall:
    symbol: str
    run_date: date
    signal: str
    confidence: float


@dataclass(frozen=True)
class AgentCard:
    agent: str
    description: str
    since: date
    profile: AgentProfile
    prompt_files: tuple[str, ...]
    snapshot: str | None
    runs: RunStats
    latest: tuple[LatestCall, ...]
    results: int
    results_with_gaps: int
    data_gaps: dict[str, int]
    violations: dict[str, int]
    llm_by_provider: tuple[UsageRow, ...]
    llm_by_prompt: tuple[UsageRow, ...]
    track: AgentTrack | None
    pending_outcomes: int
    evals: EvalCoverage | None
    hints: tuple[str, ...] = field(default=())


async def build_card(
    session: AsyncSession,
    registry: AgentRegistry,
    agent: str,
    *,
    since: date,
    today: date,
    profiles: ProfileBook,
    evals: EvalCoverage | None = None,
) -> AgentCard:
    """The card of `agent` over the market days from `since` to `today`."""
    if agent not in registry.names():
        raise KeyError(f"Unknown agent {agent!r}; known: {', '.join(sorted(registry.names()))}")
    spec = registry.get(agent)

    runs = await AgentRunRepository(session).list(agent=agent, since=since, limit=_MAX_RUNS)
    rows = await AgentResultRepository(session).recent(agent, until=today, limit=_MAX_RESULTS)
    rows = [r for r in rows if r.run_date >= since]

    gaps: Counter[str] = Counter()
    violations: Counter[str] = Counter()
    with_gaps = 0
    latest: dict[str, LatestCall] = {}
    for row in rows:  # newest first
        data = row.result_json or {}
        row_gaps = data.get("data_gaps") or []
        with_gaps += bool(row_gaps)
        gaps.update(row_gaps)
        violations.update(data.get("contract_violations") or [])
        latest.setdefault(
            row.symbol,
            LatestCall(
                row.symbol,
                row.run_date,
                str(data.get("signal", "?")),
                float(data.get("confidence") or 0.0),
            ),
        )

    llm = LLMCallRepository(session)
    started = datetime.combine(since, time.min, tzinfo=UTC)
    by_provider = await llm.usage(since=started, group_by="provider", agent=agent)
    by_prompt = await llm.usage(since=started, group_by="prompt_version", agent=agent)

    outcomes = DecisionOutcomeRepository(session)
    calls = await outcomes.scored_calls(REVIEW_HORIZON, agent=agent)
    tracks = agent_tracks(calls)
    pending = (await outcomes.status_counts(REVIEW_HORIZON)).get("pending", 0)

    card = AgentCard(
        agent=agent,
        description=spec.description,
        since=since,
        profile=profiles.resolve(agent, getattr(spec.agent_cls, "default_profile", AgentProfile())),
        prompt_files=tuple(sorted(p.name for p in PROMPTS_DIR.glob(f"{agent}*.md"))),
        snapshot=(
            str(SNAPSHOTS_DIR.relative_to(SNAPSHOTS_DIR.parents[2]) / f"{agent}.txt")
            if (SNAPSHOTS_DIR / f"{agent}.txt").exists()
            else None
        ),
        runs=_run_stats(runs),
        latest=tuple(sorted(latest.values(), key=lambda c: c.symbol)),
        results=len(rows),
        results_with_gaps=with_gaps,
        data_gaps=dict(gaps.most_common()),
        violations=dict(violations.most_common()),
        llm_by_provider=tuple(by_provider),
        llm_by_prompt=tuple(by_prompt),
        track=tracks[0] if tracks else None,
        pending_outcomes=pending,
        evals=evals,
    )
    return replace(card, hints=hints(card))


def _run_stats(runs: list) -> RunStats:
    if not runs:
        return RunStats()
    status = Counter(r.status for r in runs)
    timed = [r.analyze_ms for r in runs if r.analyze_ms is not None]
    failed = [r for r in runs if r.status == "failed" and r.error]
    return RunStats(
        total=len(runs),
        completed=status.get("completed", 0),
        failed=status.get("failed", 0),
        skipped=status.get("skipped", 0),
        llm_fallbacks=sum(r.llm_fallbacks or 0 for r in runs),
        avg_analyze_ms=sum(timed) / len(timed) if timed else None,
        last_error=failed[0].error if failed else None,  # runs are newest first
    )


def hints(card: AgentCard) -> tuple[str, ...]:
    """Where to start, most important first. Empty = nothing stands out."""
    out: list[str] = []
    executed = card.runs.completed + card.runs.failed
    if card.runs.total == 0 and card.results == 0:
        return (
            "No runs in this window: run it first — "
            f"python -m scripts.run_pipeline AAPL --agents {card.agent}",
        )
    if card.runs.failed:
        out.append(
            f"{card.runs.failed} failed run(s): fix the failure before the prompt "
            f"(last error: {card.runs.last_error})"
        )
    if card.results and card.results_with_gaps / card.results > GAP_SHARE:
        top = ", ".join(list(card.data_gaps)[:3])
        out.append(
            f"Data before prompt: {card.results_with_gaps}/{card.results} results had missing "
            f"inputs ({top}) — the model can't judge what it doesn't get"
        )
    if card.violations:
        out.append(
            "Contract violations: the answer broke a rule the prompt states — tighten the "
            f"wording or the invariant ({next(iter(card.violations))})"
        )
    if executed and card.runs.llm_fallbacks / executed > FALLBACK_SHARE:
        out.append(
            f"{card.runs.llm_fallbacks} fallback(s) in {executed} runs: a provider or quota "
            "problem, not a prompt one — check python -m scripts.preflight and /usage"
        )
    if card.evals is not None and card.evals.labelled < MIN_LABELLED_CASES:
        out.append(
            f"Only {card.evals.labelled} labelled eval case(s): add one to evals/cases.py "
            "before changing the prompt, or the eval can't tell better from worse"
        )
    if card.track is None:
        out.append(
            "No settled outcomes yet: judge changes with the scenario eval for now "
            f"({card.pending_outcomes} outcomes pending)"
        )
    return tuple(out)


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def render_card(card: AgentCard) -> str:
    p = card.profile
    lines = [
        f"Agent: {card.agent} — {card.description}",
        f"Window: {card.since.isoformat()} → today",
        "",
        "Configuration",
        f"  provider {p.provider or '(default)'} · model {p.model or '(default)'} · "
        f"prompt {p.prompt or card.agent} · skills {', '.join(p.skills) or '—'} · "
        f"use_llm {p.use_llm}",
        f"  prompt files: {', '.join(card.prompt_files) or '—'} (app/llm/prompts/)",
        f"  snapshot: {card.snapshot or '—'}",
        "",
        "Runs",
    ]
    r = card.runs
    if r.total:
        avg = f"{r.avg_analyze_ms:.0f} ms" if r.avg_analyze_ms is not None else "—"
        lines.append(
            f"  {r.total} runs: {r.completed} completed, {r.failed} failed, {r.skipped} skipped · "
            f"{r.llm_fallbacks} LLM fallbacks · avg analyze {avg}"
        )
    else:
        lines.append("  no runs yet")
    lines += ["", "Latest call per symbol"]
    lines += [
        f"  {c.symbol:<7} {c.run_date.isoformat()}  {c.signal:<8} {c.confidence:>3.0f}%"
        for c in card.latest
    ] or ["  —"]
    lines += [
        "",
        f"Data gaps: {card.results_with_gaps}/{card.results} results "
        f"({_pct(card.results_with_gaps, card.results)})",
    ]
    lines += [f"  {n:>3}× {gap}" for gap, n in card.data_gaps.items()]
    lines.append(f"Contract violations: {sum(card.violations.values())}")
    lines += [f"  {n:>3}× {v}" for v, n in card.violations.items()]
    lines += ["", "Model calls"]
    if card.llm_by_provider:
        for u in card.llm_by_provider:
            lines.append(
                f"  {u.key:<12} {u.calls:>4} calls, {u.errors} errors · "
                f"{u.input_tokens:,} in + {u.output_tokens:,} out · ${u.cost_usd:.4f}"
            )
        lines.append("  prompt versions: " + ", ".join(u.key for u in card.llm_by_prompt))
    else:
        lines.append("  —")
    lines += ["", f"Track record ({REVIEW_HORIZON} trading days vs the benchmark)"]
    if card.track is not None:
        o = card.track.overall
        rate = _pct(o.hits, o.calls)
        alpha = "—" if o.mean_alpha_captured is None else f"{o.mean_alpha_captured * 100:+.2f}%"
        lines.append(f"  {o.calls} settled calls · hit rate {rate} · alpha captured {alpha}")
        for signal, s in card.track.by_signal.items():
            if s.calls:
                lines.append(f"    {signal:<8} {_pct(s.hits, s.calls)} of {s.calls}")
    else:
        lines.append(f"  none settled yet ({card.pending_outcomes} pending)")
    if card.evals is not None:
        lines += [
            "",
            f"Eval coverage: {card.evals.cases} scenario case(s), {card.evals.labelled} labelled",
        ]
    lines += ["", "Where to start"]
    lines += [f"  - {h}" for h in card.hints] or [
        "  - nothing stands out: pick the next hypothesis"
    ]
    return "\n".join(lines)
