"""
Backtest of the recommendation's weights and thresholds against settled outcomes —
pure functions, no I/O, no model calls (docs/plans/backtest.md, part A).

Every settled (symbol, day) already has each analyst's stored signal and
confidence and the alpha that followed. A configuration (weights + BUY/SELL
thresholds) is replayed through the same `weighted_score` the pipeline uses, and
its rule-based call is scored like any other call: right or wrong, alpha captured.

Guard against overfitting: cases are split by date, the first `fit_share` of days
to rank configurations and the rest to report them. A configuration earns a change
only by beating the current one on the later days, by enough calls to matter.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain.outcomes import SettledCall, TrackStats, captured_alpha, is_hit
from app.domain.scoring import BUY_THRESHOLD, to_action, weighted_score

THRESHOLDS: tuple[float, ...] = (10.0, 15.0, 20.0, 25.0)
WEIGHT_SCALES: tuple[float, ...] = (0.0, 0.5, 1.5, 2.0)
FIT_SHARE = 0.7


@dataclass(frozen=True)
class Case:
    """One settled (symbol, day): every analyst's call that day, and what followed."""

    symbol: str
    decision_date: date
    horizon: int
    alpha: float
    results: dict[str, dict[str, Any]]  # agent → {"signal", "confidence"}
    recommended: str | None  # the stored final recommendation's signal, if any


@dataclass(frozen=True)
class Config:
    name: str
    weights: dict[str, float]
    threshold: float  # BUY above +threshold, SELL below -threshold


@dataclass(frozen=True)
class ConfigResult:
    config: Config
    fit: TrackStats
    test: TrackStats
    test_by_action: dict[str, TrackStats]


def cases_from_calls(calls: Sequence[tuple[str, SettledCall]]) -> list[Case]:
    """Group (agent, settled call) rows into one case per (symbol, day), oldest first."""
    grouped: dict[tuple[str, date], list[tuple[str, SettledCall]]] = {}
    for agent, call in calls:
        grouped.setdefault((call.symbol, call.decision_date), []).append((agent, call))
    cases = []
    for (symbol, day), rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        by_agent = {agent: call for agent, call in rows}
        first = rows[0][1]
        recommendation = by_agent.pop("recommendation", None)
        cases.append(
            Case(
                symbol=symbol,
                decision_date=day,
                horizon=first.horizon,
                alpha=first.alpha,
                results={
                    agent: {"signal": c.signal, "confidence": c.confidence}
                    for agent, c in by_agent.items()
                },
                recommended=recommendation.signal if recommendation else None,
            )
        )
    return cases


def split_by_date(cases: Sequence[Case], fit_share: float = FIT_SHARE) -> tuple[list, list]:
    """The first `fit_share` of distinct days to fit, the rest to test — never mixed in a day."""
    days = sorted({c.decision_date for c in cases})
    if len(days) < 2:
        return list(cases), []
    cut = days[min(len(days) - 1, max(1, round(len(days) * fit_share)))]
    return [c for c in cases if c.decision_date < cut], [c for c in cases if c.decision_date >= cut]


def candidate_configs(
    current: dict[str, float],
    thresholds: Sequence[float] = THRESHOLDS,
    scales: Sequence[float] = WEIGHT_SCALES,
) -> list[Config]:
    """The current weights, equal weights, and one agent rescaled at a time, per threshold."""
    weight_sets: list[tuple[str, dict[str, float]]] = [("current", dict(current))]
    total = sum(current.values())
    weight_sets.append(("equal", {a: total / len(current) for a in current}))
    for agent in current:
        for scale in scales:
            label = f"{agent} dropped" if scale == 0 else f"{agent} x{scale:g}"
            weight_sets.append((label, {**current, agent: current[agent] * scale}))
    return [
        Config(name if t == BUY_THRESHOLD else f"{name}, ±{t:g}", weights, t)
        for name, weights in weight_sets
        for t in thresholds
    ]


def rule_signal(case: Case, config: Config) -> str:
    score = weighted_score(
        case.results,
        config.weights,
        buy_threshold=config.threshold,
        sell_threshold=-config.threshold,
    )
    return score.base_signal


def stats(signals: Sequence[str], cases: Sequence[Case]) -> TrackStats:
    if not cases:
        return TrackStats(0, 0, None)
    hits = sum(is_hit(s, c.alpha, c.horizon) for s, c in zip(signals, cases, strict=True))
    captured = [captured_alpha(s, c.alpha) for s, c in zip(signals, cases, strict=True)]
    return TrackStats(len(cases), hits, sum(captured) / len(captured))


def evaluate(config: Config, fit: Sequence[Case], test: Sequence[Case]) -> ConfigResult:
    fit_signals = [rule_signal(c, config) for c in fit]
    test_signals = [rule_signal(c, config) for c in test]
    by_action: dict[str, TrackStats] = {}
    for action in ("BUY", "HOLD", "SELL"):
        picked = [(s, c) for s, c in zip(test_signals, test, strict=True) if to_action(s) == action]
        if picked:
            by_action[action] = stats([s for s, _ in picked], [c for _, c in picked])
    return ConfigResult(config, stats(fit_signals, fit), stats(test_signals, test), by_action)


def run(
    cases: Sequence[Case], current: dict[str, float], fit_share: float = FIT_SHARE
) -> tuple[list[ConfigResult], TrackStats]:
    """
    Every candidate, ranked by alpha captured on the fit days (then hit rate), and the
    stored LLM recommendations' own record on the test days, for comparison.
    """
    fit, test = split_by_date(cases, fit_share)
    results = [evaluate(c, fit, test) for c in candidate_configs(current)]
    results.sort(
        key=lambda r: (r.fit.mean_alpha_captured or 0.0, r.fit.hit_rate or 0.0), reverse=True
    )
    with_llm = [c for c in test if c.recommended is not None]
    llm = stats([c.recommended or "neutral" for c in with_llm], with_llm)
    return results, llm
