import pytest

from app.domain.valuation import (
    DCF_SCENARIOS,
    DcfScenario,
    dcf_scenarios,
    dcf_value,
    ev_ebitda_value,
    owner_earnings_value,
    summarize,
    with_fmp_fallbacks,
)


@pytest.mark.unit
def test_dcf_value_matches_hand_calculation() -> None:
    flat = DcfScenario(growth_1=0.0, growth_2=0.0, terminal_growth=0.0, wacc=0.10)
    # 10 years of 100 at 10% + perpetuity 1000 discounted 10 years, × 0.85 haircut
    annuity = sum(100 / 1.1**t for t in range(1, 11))
    terminal = 1000 / 1.1**10
    assert dcf_value(100, flat) == pytest.approx((annuity + terminal) * 0.85)


@pytest.mark.unit
def test_dcf_invalid_when_wacc_not_above_growth() -> None:
    assert dcf_value(100, DcfScenario(0.1, 0.1, terminal_growth=0.1, wacc=0.1)) == 0.0


@pytest.mark.unit
def test_scenarios_are_ordered_and_fallback_to_operating_income() -> None:
    values = dcf_scenarios({"freeCashflow": 1e9})
    assert values["bear"] < values["base"] < values["bull"]
    assert set(values) == set(DCF_SCENARIOS)
    assert dcf_scenarios({"freeCashflow": -1, "operatingIncome": 1e9})["base"] > 0
    assert dcf_scenarios({}) == {"bear": 0.0, "base": 0.0, "bull": 0.0}


@pytest.mark.unit
def test_owner_earnings_and_ev_ebitda() -> None:
    assert owner_earnings_value(
        {"netIncomeToCommon": 100, "depreciation": 20, "capitalExpenditures": -50}
    ) == (pytest.approx((100 + 20 - 40) * 12))
    assert owner_earnings_value({"netIncomeToCommon": -1}) is None
    assert owner_earnings_value({"netIncome": 10, "capitalExpenditures": -100}) is None
    tech = {"ebitda": 100, "sector": "Technology", "totalDebt": 300, "totalCash": 50}
    assert ev_ebitda_value(tech) == 100 * 20 - 300 + 50
    assert ev_ebitda_value({"ebitda": 100, "sector": "Unknown"}) == 1200
    assert ev_ebitda_value({"ebitda": 0}) is None


@pytest.mark.unit
def test_summary_signals_by_margin_of_safety() -> None:
    cheap = {"freeCashflow": 10e9, "marketCap": 50e9, "ebitda": 15e9, "netIncomeToCommon": 8e9}
    rich = {**cheap, "marketCap": 2_000e9}
    assert summarize(cheap).signal == "bullish"
    assert summarize(rich).signal == "bearish"
    intrinsic = summarize(cheap).avg_intrinsic_value
    fair = summarize({**cheap, "marketCap": intrinsic})
    assert (fair.signal, fair.confidence) == ("neutral", 50.0)
    assert fair.margin_of_safety == pytest.approx(0.0)
    # A market cap but no intrinsic estimate is no evidence, not a fair price
    unknown = summarize({"marketCap": 100.0})
    assert (unknown.signal, unknown.confidence, unknown.margin_of_safety) == ("neutral", 0.0, 0.0)


@pytest.mark.unit
def test_fcf_fallback_only_when_missing() -> None:
    assert with_fmp_fallbacks({}, [{"freeCashFlow": 5}], {}) == {"freeCashflow": 5}
    assert with_fmp_fallbacks({"freeCashflow": 1}, [{"freeCashFlow": 5}], {}) == {"freeCashflow": 1}
    assert with_fmp_fallbacks({}, [], {}) == {}
    # yfinance info with only a quote: the market cap comes from FMP's profile
    quote_only = {"regularMarketPrice": 517.0}
    filled = with_fmp_fallbacks(quote_only, [], {"marketCap": 3.8e12})
    assert filled == {"regularMarketPrice": 517.0, "marketCap": 3.8e12}
    assert with_fmp_fallbacks({"marketCap": 1.0}, [], {"marketCap": 2.0})["marketCap"] == 1.0


@pytest.mark.unit
def test_no_market_cap_means_no_valuation_not_a_huge_margin_of_safety() -> None:
    # Live run, MSFT: info had a price but no marketCap / sharesOutstanding, and the
    # market cap fell back to price x 1 share -> "intrinsic value vastly exceeds market
    # cap", bullish 90%. Now: neutral at 0% confidence, nothing to compare against.
    info = {"regularMarketPrice": 517.0, "freeCashflow": 7e10, "ebitda": 1.5e11}
    v = summarize(info)
    assert v.avg_intrinsic_value > 0
    assert (v.market_cap, v.margin_of_safety, v.signal, v.confidence) == (0.0, 0.0, "neutral", 0.0)
    # With shares, the market cap is price x shares again
    assert summarize({**info, "sharesOutstanding": 7.4e9}).market_cap == pytest.approx(
        517.0 * 7.4e9
    )
