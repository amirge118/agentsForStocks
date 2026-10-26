import pytest

from app.domain.fundamentals import (
    score_financial_health,
    score_growth,
    score_profitability,
    score_valuation,
    vote,
)

STRONG = {
    "returnOnEquity": 0.30,
    "profitMargins": 0.25,
    "operatingMargins": 0.30,
    "revenueGrowth": 0.15,
    "earningsGrowth": 0.20,
    "bookValue": 4.0,
    "currentRatio": 2.0,
    "debtToEquity": 30,
    "freeCashflow": 1e9,
    "trailingPE": 15,
    "priceToBook": 2,
    "priceToSalesTrailing12Months": 3,
}


@pytest.mark.unit
def test_strong_company_is_unanimously_bullish() -> None:
    result = vote(STRONG)
    assert result.majority == "bullish"
    assert result.agreeing == 4
    assert result.confidence == 100.0


@pytest.mark.unit
def test_empty_info_does_not_crash_and_is_not_bullish() -> None:
    """Regression: None fields used to raise TypeError in the f-string details."""
    info = {key: None for key in STRONG}
    result = vote(info)
    assert result.majority in ("bearish", "neutral")
    assert "N/A" in result.factors[0].detail


@pytest.mark.unit
def test_expensive_valuation_is_bearish() -> None:
    expensive = {"trailingPE": 60, "priceToBook": 20, "priceToSalesTrailing12Months": 10}
    assert score_valuation(expensive).signal == "bearish"
    assert score_valuation({"trailingPE": 60}).signal == "neutral"


@pytest.mark.unit
def test_individual_factor_thresholds() -> None:
    assert score_profitability({"returnOnEquity": 0.2}).signal == "neutral"
    assert score_growth(
        {"revenueGrowth": 0.01, "earningsGrowth": -0.2, "bookValue": -3}
    ).signal == ("bearish")
    weak = {"currentRatio": 0.5, "debtToEquity": 200, "freeCashflow": -1}
    assert score_financial_health(weak).signal == "bearish"
    assert "FCF=neg" in score_financial_health(weak).detail


@pytest.mark.unit
def test_split_vote_is_neutral() -> None:
    info = {
        **STRONG,
        "revenueGrowth": 0,
        "earningsGrowth": 0,
        "bookValue": 0,
        "trailingPE": 60,
        "priceToBook": 20,
    }
    assert vote(info).majority == "neutral"


@pytest.mark.unit
def test_missing_fields_are_no_evidence_not_a_failure() -> None:
    # A field yfinance didn't return used to count as 0: no ROE = failed check,
    # no P/E = "cheap". With no data the vote said bearish at 75%.
    empty = vote({})
    assert (empty.majority, empty.agreeing, empty.confidence) == ("neutral", 0, 0.0)
    assert all(not f.has_data and f.detail.endswith("(no data)") for f in empty.factors)
    assert score_valuation({}).signal == "neutral"  # no multiples is not "cheap"
    # Partial data: only the factors with data vote, out of all four
    partial = vote({"returnOnEquity": 0.3, "profitMargins": 0.3, "operatingMargins": 0.3})
    assert (partial.majority, partial.agreeing, partial.confidence) == ("bullish", 1, 25.0)
    # Financial health judges the fields that exist and shows the rest as N/A
    health = score_financial_health({"currentRatio": 2.0, "freeCashflow": 5e9})
    assert health.signal == "bullish" and "D/E=N/A" in health.detail
