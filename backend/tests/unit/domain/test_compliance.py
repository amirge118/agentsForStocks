"""Unit tests for the rule-based recommendation compliance review."""

import pytest

from app.domain.compliance import ComplianceFinding, review_recommendation


@pytest.mark.unit
def test_balanced_bullish_text_passes() -> None:
    review = review_recommendation(
        "Strong margins and growth; main risk is a rich valuation.", "bullish"
    )
    assert review.status == "pass"
    assert review.findings == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Returns are guaranteed given the moat.",
        "A risk-free compounder with pricing power and low debt.",
        "You can't lose here despite the volatility.",
        "This stock is a sure thing, valuation aside.",
    ],
)
def test_promissory_language_fails(text: str) -> None:
    review = review_recommendation(text, "bullish")
    assert review.status == "fail"
    assert any(f.rule == "promissory_language" for f in review.findings)


@pytest.mark.unit
def test_negated_guarantee_is_allowed() -> None:
    review = review_recommendation("Upside is not guaranteed; downside risk from debt.", "bullish")
    assert review.status == "pass"


@pytest.mark.unit
def test_exaggerated_claim_flags() -> None:
    review = review_recommendation("A no-brainer buy, though competition is a risk.", "bullish")
    assert review.status == "flag"
    assert review.findings[0].rule == "exaggerated_claim"


@pytest.mark.unit
def test_bullish_without_risk_flags() -> None:
    review = review_recommendation("Great growth and strong margins.", "bullish")
    assert review.status == "flag"
    assert review.findings[0].rule == "missing_risk_discussion"


@pytest.mark.unit
def test_bearish_without_risk_terms_passes() -> None:
    assert (
        review_recommendation("Revenue shrinking and margins falling.", "bearish").status == "pass"
    )


@pytest.mark.unit
def test_findings_report_the_matched_phrase() -> None:
    review = review_recommendation("Guaranteed winner.", "bullish")
    assert review.status == "fail"
    assert ComplianceFinding("promissory_language", "fail", "Guaranteed") in review.findings
