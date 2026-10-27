"""
Eval cases.

scenarios — the company archetypes from tests/scenarios.py run through the real
agents. Where the data make the right call unambiguous, the case carries the
expected signals and a confidence ceiling; other cases are graded for
stability, contracts, faithfulness and cost only.

ledger — real (system, user) prompts captured from llm_calls (evals.capture)
and replayed against the configuration under test.

outcomes — ledger cases whose decision has a settled outcome (evals.capture
--outcomes): graded against the alpha that followed — hit rate and alpha captured.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tests import scenarios
from tests.factories import FakeResults

ANALYST_AGENTS = (
    "financial_history",
    "valuation",
    "moat",
    "risk",
    "broad_analysis",
    "growth",
    "institutional",
    "earnings",
    "fundamentals",
    "technicals",
    "sentiment",
    "market_scanner",
)


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    agent: str
    scenario: Callable[[], scenarios.Scenario] | None = None
    # For the recommendation agent: the analyst results it builds on
    analysts: dict[str, dict] | None = None
    # Replayed ledger cases
    system: str | None = None
    prompt: str | None = None
    reference: str | None = None
    expected: frozenset[str] | None = None
    max_confidence: float | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    # Outcome cases: the alpha vs the benchmark after `outcome_horizon` sessions
    outcome_alpha: float | None = None
    outcome_horizon: int | None = None

    @property
    def labelled(self) -> bool:
        return self.expected is not None or self.max_confidence is not None

    def results(self) -> FakeResults | None:
        return FakeResults(self.analysts) if self.analysts is not None else None


def _expect(*signals: str) -> frozenset[str]:
    return frozenset(signals)


def _analysts(signal: str, confidence: float, **overrides: dict) -> dict[str, dict]:
    from app.agents.catalog import load_agents

    weighted = load_agents().weights()
    base = {n: {"signal": signal, "confidence": confidence, "reasoning": "ok"} for n in weighted}
    base.update(overrides)
    return base


def scenario_suite() -> list[EvalCase]:
    cases = [
        EvalCase(
            f"no_data/{a}", a, scenarios.no_data, expected=_expect("neutral"), max_confidence=25
        )
        for a in ANALYST_AGENTS
    ]
    cases += [
        EvalCase(
            "overvalued/valuation", "valuation", scenarios.overvalued, expected=_expect("bearish")
        ),
        EvalCase(
            "baseline/valuation",
            "valuation",
            scenarios.baseline,
            expected=_expect("neutral", "bearish"),
        ),
        EvalCase(
            "uptrend/technicals", "technicals", scenarios.uptrend, expected=_expect("bullish")
        ),
        EvalCase(
            "downtrend/technicals",
            "technicals",
            scenarios.downtrend,
            expected=_expect("bearish", "neutral"),
        ),
        EvalCase(
            "distressed/fundamentals",
            "fundamentals",
            scenarios.distressed,
            expected=_expect("bearish"),
        ),
        EvalCase("distressed/risk", "risk", scenarios.distressed, expected=_expect("bearish")),
        EvalCase(
            "distressed/financial_history",
            "financial_history",
            scenarios.distressed,
            expected=_expect("bearish"),
        ),
        EvalCase(
            "distressed/valuation",
            "valuation",
            scenarios.distressed,
            expected=_expect("bearish", "neutral"),
        ),
        EvalCase(
            "consensus/recommendation",
            "recommendation",
            analysts=_analysts("bullish", 75.0),
            expected=_expect("bullish"),
        ),
        EvalCase(
            "risk_override/recommendation",
            "recommendation",
            analysts=_analysts(
                "bullish",
                75.0,
                risk={"signal": "bearish", "confidence": 85.0, "reasoning": "covenant breach"},
            ),
            expected=_expect("neutral"),
            max_confidence=55,
        ),
    ]
    cases += [
        EvalCase(f"baseline/{a}", a, scenarios.baseline, tags=("unlabelled",))
        for a in ANALYST_AGENTS
        if a != "valuation"
    ]
    return cases


def ledger_suite(path: Path) -> list[EvalCase]:
    """Cases exported by evals.capture: one JSON object per line."""
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        outcome = row.get("outcome") or {}
        cases.append(
            EvalCase(
                case_id=f"ledger/{row['call_id']}",
                agent=row["agent"],
                system=row["system_prompt"],
                prompt=row["prompt"],
                reference=row.get("response"),
                expected=frozenset(row["expected"]) if row.get("expected") else None,
                tags=("ledger", row.get("prompt_name") or ""),
                outcome_alpha=outcome.get("alpha"),
                outcome_horizon=outcome.get("horizon"),
            )
        )
    return cases


def outcome_suite(path: Path) -> list[EvalCase]:
    """Ledger cases that carry a settled outcome (exported with evals.capture --outcomes)."""
    return [c for c in ledger_suite(path) if c.outcome_alpha is not None]


def select(cases: list[EvalCase], agents: list[str] | None) -> list[EvalCase]:
    return [c for c in cases if not agents or c.agent in agents]
