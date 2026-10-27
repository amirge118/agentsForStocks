from datetime import date, timedelta

import pytest

from app.domain.backtest import (
    Case,
    Config,
    candidate_configs,
    cases_from_calls,
    rule_signal,
    run,
    split_by_date,
)
from app.domain.outcomes import SettledCall

START = date(2026, 6, 1)


def case(day: int, alpha: float, good: str, bad: str, recommended: str | None = None) -> Case:
    return Case(
        symbol="AAPL",
        decision_date=START + timedelta(days=day),
        horizon=20,
        alpha=alpha,
        results={
            "good": {"signal": good, "confidence": 80.0},
            "bad": {"signal": bad, "confidence": 80.0},
        },
        recommended=recommended,
    )


def history(days: int = 20) -> list[Case]:
    """'good' always calls the direction that followed; 'bad' always the opposite."""
    cases = []
    for d in range(days):
        up = d % 2 == 0
        cases.append(
            case(
                d,
                0.03 if up else -0.03,
                "bullish" if up else "bearish",
                "bearish" if up else "bullish",
                recommended="bullish",
            )
        )
    return cases


# The bad agent outweighs the good one: 0.8 x (25 - 40) = -12, a HOLD at ±15 every day
CURRENT = {"good": 25.0, "bad": 40.0}


@pytest.mark.unit
def test_a_bad_agent_dropped_wins_out_of_sample() -> None:
    results, llm = run(history(), CURRENT)

    best = results[0]
    assert best.config.weights["bad"] == 0  # dropped (at any threshold that still trades)
    assert best.test.hit_rate == 1.0 and best.test.mean_alpha_captured == pytest.approx(0.03)

    current = next(r for r in results if r.config.name == "current")
    assert current.test.hit_rate == 0.0  # holds through ±3% moves: wrong, nothing captured
    assert current.test.mean_alpha_captured == 0.0
    assert set(current.test_by_action) == {"HOLD"}
    # At ±10 the current weights follow the bad agent: wrong every time
    tight = next(r for r in results if r.config.name == "current, ±10")
    assert tight.test.mean_alpha_captured == pytest.approx(-0.03)
    assert set(tight.test_by_action) == {"BUY", "SELL"}
    # Always-bullish stored recommendations: right on the up days only
    assert llm.calls == 6 and llm.hit_rate == pytest.approx(0.5)


@pytest.mark.unit
def test_split_keeps_days_whole_and_ordered() -> None:
    cases = history(10) + [case(9, 0.01, "neutral", "neutral")]  # two cases on the last day
    fit, test = split_by_date(cases, 0.7)
    assert max(c.decision_date for c in fit) < min(c.decision_date for c in test)
    assert len(fit) == 7 and len(test) == 4
    assert split_by_date(history(1)) == (history(1), [])


@pytest.mark.unit
def test_thresholds_decide_between_hold_and_a_call() -> None:
    c = case(0, 0.01, "bullish", "neutral")  # score = 0.8 * 20 = +16
    weights = {"good": 20.0, "bad": 10.0}
    assert rule_signal(c, Config("t15", weights, 15.0)) == "bullish"
    assert rule_signal(c, Config("t20", weights, 20.0)) == "neutral"


@pytest.mark.unit
def test_candidates_cover_current_equal_and_each_agent() -> None:
    configs = candidate_configs({"a": 10.0, "b": 30.0}, thresholds=(15.0, 20.0), scales=(0.0, 2.0))
    names = [c.name for c in configs]
    assert names[:2] == ["current", "current, ±20"]
    assert "equal" in names and "a dropped" in names and "b x2, ±20" in names
    assert len(configs) == (2 + 2 * 2) * 2
    equal = next(c for c in configs if c.name == "equal")
    assert equal.weights == {"a": 20.0, "b": 20.0}


@pytest.mark.unit
def test_cases_from_calls_groups_agents_by_day() -> None:
    def call(symbol: str, day: int, signal: str, alpha: float = 0.02) -> SettledCall:
        d = START + timedelta(days=day)
        return SettledCall(
            symbol, d, d + timedelta(days=28), 20, "SPY", signal, 70.0, "", 0.0, alpha
        )

    cases = cases_from_calls(
        [
            ("moat", call("MSFT", 1, "bullish")),
            ("recommendation", call("AAPL", 2, "bearish")),
            ("moat", call("AAPL", 2, "bullish")),
            ("risk", call("AAPL", 2, "neutral")),
        ]
    )
    assert [(c.symbol, c.decision_date.day) for c in cases] == [("MSFT", 2), ("AAPL", 3)]
    aapl = cases[1]
    assert aapl.recommended == "bearish" and set(aapl.results) == {"moat", "risk"}
    assert aapl.results["moat"] == {"signal": "bullish", "confidence": 70.0}
    assert cases[0].recommended is None
