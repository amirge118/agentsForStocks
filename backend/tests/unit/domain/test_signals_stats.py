import pytest

from app.domain.signals import clamp, direction, label_from_score
from app.domain.stats import cagr, find_keywords, mean, sample_variance


@pytest.mark.unit
def test_direction_and_labels() -> None:
    assert [direction(s) for s in ("bullish", "bearish", "neutral", "junk")] == [1, -1, 0, 0]
    assert label_from_score(0.2) == "bullish"
    assert label_from_score(-0.2) == "bearish"
    assert label_from_score(0.19) == "neutral"
    assert clamp(5, -1, 1) == 1


@pytest.mark.unit
def test_mean_and_variance() -> None:
    assert mean([]) == 0.0
    assert mean([1, 2, 3]) == 2
    assert sample_variance([1.0]) == 0.0
    assert sample_variance([1.0, 3.0]) == 2.0


@pytest.mark.unit
def test_cagr_newest_first() -> None:
    rows = [{"revenue": 121.0}, {"revenue": 110.0}, {"revenue": 100.0}]
    assert cagr(rows, "revenue") == pytest.approx(0.10)


@pytest.mark.unit
@pytest.mark.parametrize(
    "rows",
    [[], [{"revenue": 1}], [{"revenue": 5}, {"revenue": -1}], [{"x": 1}, {"x": None}]],
)
def test_cagr_degenerate_inputs_return_zero(rows: list[dict]) -> None:
    assert cagr(rows, "revenue") == 0.0


@pytest.mark.unit
def test_find_keywords_case_insensitive() -> None:
    assert find_keywords("Strong BRAND and Patents", ["patent", "brand", "moat"]) == [
        "patent",
        "brand",
    ]
