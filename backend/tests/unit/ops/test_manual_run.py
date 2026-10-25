from datetime import date

import pytest

from app.agents.base import AnalysisResult
from app.agents.runner import RunOutcome
from app.ops.manual_run import render_report
from app.pipeline.orchestrator import PipelineReport


class _Rec(AnalysisResult):
    action: str


@pytest.mark.unit
def test_render_report_lists_every_outcome() -> None:
    moat = AnalysisResult(signal="bullish", confidence=70, reasoning="Brand", summary="s")
    rec = _Rec(signal="bullish", confidence=66, reasoning="Buy it", summary="s", action="BUY")
    report = PipelineReport(
        "p1",
        date(2026, 10, 23),
        outcomes=(
            RunOutcome("recommendation", "AAPL", "r3", "completed", result=rec),
            RunOutcome("moat", "AAPL", "r1", "completed", result=moat),
            RunOutcome("risk", "AAPL", "r2", "failed", error="HTTP 403"),
            RunOutcome("growth", "AAPL", "r4", "skipped"),
        ),
    )
    text = render_report(report)
    lines = text.splitlines()
    assert lines[0] == "Pipeline p1 for 2026-10-23: 2 completed, 1 failed, 1 skipped"
    assert [line.split()[1] for line in lines[2:6]] == ["growth", "moat", "recommendation", "risk"]
    assert lines[-1] == "LLM: 0 calls, 0 input + 0 output tokens, $0.0000, 0 fallbacks"
    assert "bullish   70%  Brand" in text
    assert "66% BUY  Buy it" in text
    assert "failed    HTTP 403" in text


@pytest.mark.unit
def test_render_report_shows_llm_usage() -> None:
    from app.core.context import RunUsage

    moat = AnalysisResult(signal="bullish", confidence=70, reasoning="Brand", summary="s")
    usage = RunUsage(llm_calls=1, input_tokens=1200, output_tokens=80, cost_usd=0.0016)
    report = PipelineReport(
        "p1",
        date(2026, 10, 23),
        outcomes=(RunOutcome("moat", "AAPL", "r1", "completed", result=moat, usage=usage),),
    )
    text = render_report(report)
    assert "[1200+80 tok]" in text
    assert text.splitlines()[-1] == (
        "LLM: 1 calls, 1,200 input + 80 output tokens, $0.0016, 0 fallbacks"
    )
