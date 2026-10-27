import pytest

from app.domain.backtest import Config, ConfigResult
from app.domain.outcomes import TrackStats
from app.ops.backtest import render_backtest


def result(name: str, fit: TrackStats, test: TrackStats) -> ConfigResult:
    return ConfigResult(Config(name, {"a": 1.0}, 15.0), fit, test, {})


@pytest.mark.unit
def test_render_backtest() -> None:
    empty = [result("current", TrackStats(0, 0, None), TrackStats(0, 0, None))]
    assert "Not enough settled days yet" in render_backtest(empty, TrackStats(0, 0, None), 20)

    ranked = [
        result("risk dropped", TrackStats(14, 10, 0.012), TrackStats(6, 4, 0.008)),
        result("current", TrackStats(14, 7, 0.002), TrackStats(6, 3, -0.001)),
    ]
    text = render_backtest(ranked, TrackStats(5, 3, 0.004), 20, top=5)
    lines = text.splitlines()
    assert "first 14 cases (fit), reported on the 6 later" in lines[1]
    current = next(line for line in lines if line.startswith("*current"))
    assert current.split()[1:] == ["14", "50%", "+0.20%", "6", "50%", "-0.10%"]
    assert next(line for line in lines if "risk dropped" in line).split()[-3:] == [
        "6",
        "67%",
        "+0.80%",
    ]
    assert sum("current" in line for line in lines[:8]) == 1  # current shown once, first
    llm = next(line for line in lines if "LLM recommendation" in line)
    assert llm.split()[-3:] == ["5", "60%", "+0.40%"]
