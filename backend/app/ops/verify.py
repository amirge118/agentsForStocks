"""
End-to-end check of a real run (`python -m scripts.verify`): every agent on a few
symbols, then a report of what the data look like — so after bringing the stack up
you know it works, and you see where the analysis is weak.

PASS  every agent ran and every judgement came from a model
WARN  everything ran, but some results need review (a fallback stood in for the model)
FAIL  an agent run failed

Missing inputs are listed but don't change the verdict: some are expected (FMP's
free plan has no institutional holders; Yahoo news is blocked on some hosts).

The report reads the stored results of the run date, so a symbol already analysed
today (skipped: runs are idempotent) is reported from what is stored.
"""

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.registry import AgentRegistry
from app.pipeline.orchestrator import PipelineReport
from app.repositories.agent_results import AgentResultRepository
from app.repositories.provider_calls import ProviderCallRepository

Verdict = Literal["PASS", "WARN", "FAIL"]
RECOMMENDATION = "recommendation"
_ARROW = {"bullish": "▲", "bearish": "▼", "neutral": "·"}


@dataclass(frozen=True)
class AgentCell:
    signal: str
    confidence: float
    data_gaps: list[str]
    needs_review: list[str]
    contract_violations: list[str]


@dataclass(frozen=True)
class SymbolView:
    symbol: str
    action: str | None
    score: float | None
    confidence: float | None
    reasoning: str
    agents: dict[str, AgentCell]


@dataclass(frozen=True)
class VerifyReport:
    run_date: date
    counts: dict[str, int]
    failed: list[str]  # "agent/SYMBOL: error"
    symbols: list[SymbolView]
    llm: dict[str, int | float]
    fmp_calls_today: int
    notes: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> list[str]:
        return [
            f"{agent}/{s.symbol}: {'; '.join(cell.needs_review)}"
            for s in self.symbols
            for agent, cell in s.agents.items()
            if cell.needs_review
        ]

    @property
    def data_gaps(self) -> dict[str, Counter[str]]:
        """agent → {missing input: symbols that lacked it}."""
        gaps: dict[str, Counter[str]] = defaultdict(Counter)
        for s in self.symbols:
            for agent, cell in s.agents.items():
                gaps[agent].update(cell.data_gaps)
        return dict(gaps)

    @property
    def violations(self) -> list[str]:
        return [
            f"{agent}/{s.symbol}: {v}"
            for s in self.symbols
            for agent, cell in s.agents.items()
            for v in cell.contract_violations
        ]

    @property
    def verdict(self) -> Verdict:
        if self.failed:
            return "FAIL"
        if self.needs_review:
            return "WARN"
        return "PASS"

    def to_json(self) -> str:
        """The whole report, for comparing runs over time."""
        body: dict[str, Any] = asdict(self)
        body["run_date"] = self.run_date.isoformat()
        body["verdict"] = self.verdict
        return json.dumps(body, indent=2, ensure_ascii=False)


async def build_report(
    session_factory: async_sessionmaker[AsyncSession],
    registry: AgentRegistry,
    report: PipelineReport,
    symbols: list[str],
) -> VerifyReport:
    agents = [name for level in registry.execution_levels() for name in level]
    views = []
    async with session_factory() as session:
        results = AgentResultRepository(session)
        for symbol in symbols:
            stored = await results.get_for_date(symbol, report.run_date, agents)
            views.append(_symbol_view(symbol, stored))
        fmp = await ProviderCallRepository(session).count("fmp", report.run_date)
    return VerifyReport(
        run_date=report.run_date,
        counts=report.counts,
        failed=[f"{o.agent}/{o.symbol}: {o.error}" for o in report.failed],
        symbols=views,
        llm=report.usage,
        fmp_calls_today=fmp,
        notes=[
            f"{n} agent runs were already done today and were read from the database "
            "(add --force to run them again)"
            for n in [report.counts.get("skipped", 0)]
            if n
        ],
    )


def _symbol_view(symbol: str, stored: dict[str, dict[str, Any]]) -> SymbolView:
    rec = stored.get(RECOMMENDATION, {})
    cells = {
        agent: AgentCell(
            signal=str(result.get("signal", "?")),
            confidence=float(result.get("confidence") or 0.0),
            data_gaps=list(result.get("data_gaps") or []),
            needs_review=list(result.get("needs_review") or []),
            contract_violations=list(result.get("contract_violations") or []),
        )
        for agent, result in stored.items()
    }
    return SymbolView(
        symbol=symbol,
        action=rec.get("action"),
        score=rec.get("weighted_score"),
        confidence=rec.get("confidence"),
        reasoning=str(rec.get("reasoning", "")),
        agents=cells,
    )


def render(report: VerifyReport) -> str:
    lines = [f"Run of {report.run_date}: " + _counts(report.counts), ""]

    lines.append("Recommendations")
    for s in report.symbols:
        if s.action is None:
            lines.append(f"  {s.symbol:<6} no recommendation (a fund, or the run failed)")
            continue
        lines.append(
            f"  {s.symbol:<6} {s.action:<4} score {s.score:+6.1f}  {s.confidence:3.0f}%  "
            f"{s.reasoning[:90]}"
        )

    agents = sorted({a for s in report.symbols for a in s.agents} - {RECOMMENDATION})
    if agents:
        lines += ["", "Signals (▲ bullish · neutral ▼ bearish, confidence; ! = needs review)"]
        lines.append("  " + " " * 18 + "".join(f"{s.symbol:>9}" for s in report.symbols))
        for agent in agents:
            row = "".join(_cell(s.agents.get(agent)) for s in report.symbols)
            lines.append(f"  {agent:<18}{row}")

    gaps = {a: c for a, c in report.data_gaps.items() if c}
    if gaps:
        lines += ["", "Missing inputs (the agent ran without them)"]
        for agent, counter in sorted(gaps.items()):
            items = ", ".join(f"{name} ({n}/{len(report.symbols)})" for name, n in counter.items())
            lines.append(f"  {agent:<18} {items}")
    for title, items in (
        ("Needs review (a fallback stood in for the model)", report.needs_review),
        ("Contract violations (an agent broke its own rule)", report.violations),
        ("Failed agent runs", report.failed),
    ):
        if items:
            lines += ["", title] + [f"  {item}" for item in items]

    u = report.llm
    lines += [
        "",
        f"LLM: {u.get('llm_calls', 0)} calls, ${u.get('cost_usd', 0):.4f}, "
        f"{u.get('llm_fallbacks', 0)} fallbacks · FMP: {report.fmp_calls_today} calls today",
    ]
    lines += report.notes
    lines += ["", f"{report.verdict}: {_verdict_text(report)}"]
    return "\n".join(lines)


def _cell(cell: AgentCell | None) -> str:
    if cell is None:
        return f"{'—':>9}"
    flag = "!" if cell.needs_review else " "
    return f"{_ARROW.get(cell.signal, '?')}{cell.confidence:4.0f}%{flag}".rjust(9)


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {status}" for status, n in sorted(counts.items())) or "nothing ran"


def _verdict_text(report: VerifyReport) -> str:
    if report.verdict == "FAIL":
        return f"{len(report.failed)} agent runs failed — see above, then the api/worker logs"
    if report.verdict == "WARN":
        return (
            f"everything ran, but {len(report.needs_review)} results need review — usually a "
            "free model's rate limit; run again later, or set ANTHROPIC_API_KEY"
        )
    return "every agent ran on every symbol, every judgement came from a model"
