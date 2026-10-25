import pytest

from app.agents.base import AnalysisResult, ComplianceView
from app.agents.compliance import apply_compliance, withheld_reasoning
from app.domain.compliance import review_text


def _result(reasoning: str, summary: str | None = None, signal: str = "bullish") -> AnalysisResult:
    return AnalysisResult(
        signal=signal,
        confidence=65,
        reasoning=reasoning,
        summary=summary if summary is not None else f"Moat: {signal} (65%) — {reasoning}",
    )


@pytest.mark.unit
def test_clean_reasoning_passes_and_is_kept() -> None:
    # Single-analyst reasoning is not required to discuss risk
    result = apply_compliance("moat", "AAPL", _result("Strong brand and switching costs."))

    assert result.reasoning == "Strong brand and switching costs."
    assert result.compliance == ComplianceView(status="pass", findings=[])


@pytest.mark.unit
def test_hype_is_flagged_but_kept() -> None:
    result = apply_compliance("growth", "AAPL", _result("Revenue set to skyrocket."))

    assert result.reasoning == "Revenue set to skyrocket."
    assert result.compliance is not None
    assert result.compliance.status == "flag"
    assert result.compliance.findings[0].rule == "exaggerated_claim"


@pytest.mark.unit
def test_promissory_reasoning_and_summary_are_replaced() -> None:
    text = "A risk-free compounder."
    result = apply_compliance("moat", "AAPL", _result(text))

    assert result.reasoning == withheld_reasoning("bullish", 65)
    assert result.summary == f"Moat: bullish (65%) — {withheld_reasoning('bullish', 65)}"
    assert result.compliance is not None
    assert result.compliance.status == "fail"
    assert result.compliance.original_reasoning == text
    assert result.signal == "bullish" and result.confidence == 65


@pytest.mark.unit
def test_summary_rebuilt_when_it_does_not_contain_the_reasoning_verbatim() -> None:
    result = apply_compliance(
        "sentiment", "AAPL", _result("Guaranteed winner.", summary="Sentiment: guaranteed winner")
    )

    assert result.summary == f"sentiment: bullish (65%) — {withheld_reasoning('bullish', 65)}"


@pytest.mark.unit
def test_withheld_notice_itself_passes_review() -> None:
    for signal in ("bullish", "bearish", "neutral"):
        text = withheld_reasoning(signal, 80)
        assert review_text(text, signal, require_risk_discussion=False).status == "pass"


@pytest.mark.unit
def test_result_with_its_own_review_is_untouched() -> None:
    own = _result("Guaranteed.").model_copy(
        update={"compliance": ComplianceView(status="pass", findings=[])}
    )
    assert apply_compliance("recommendation", "AAPL", own) is own
