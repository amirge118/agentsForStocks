import pytest

from app.ops.token_report import render_usage
from app.repositories.llm_calls import UsageRow


@pytest.mark.unit
def test_render_usage_table() -> None:
    assert render_usage([], "agent", 7) == "No LLM calls in the last 7 days."
    rows = [
        UsageRow("moat", 2, 0, 3400, 120, 0, 0, 0.0040, 830.0),
        UsageRow("risk", 1, 1, 2200, 60, 0, 0, 0.0025, 910.0),
    ]
    text = render_usage(rows, "agent", 7)
    assert "moat" in text and "risk" in text
    assert text.splitlines()[-1].split()[:4] == ["total", "3", "1", "5,600"]
