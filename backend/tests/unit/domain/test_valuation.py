import pytest

from app.domain.valuation import (
    DEFAULT_GROWTH,
    MAX_GROWTH,
    DcfScenario,
    dcf_value,
    discount_rate,
    earnings_power_value,
    ev_ebitda_value,
    growth_estimate,
    implied_growth,
    normalized_cash_flow,
    owner_earnings,
    scenarios,
    summarize,
    with_fmp_fallbacks,
)

# Live inputs, 2026-10-26 (Yahoo chart + FMP stable), in USD
AAPL = {
    "marketCap": 5.019e12,
    "freeCashflow": 98.767e9,
    "netIncomeToCommon": 112.010e9,
    "depreciation": 11.698e9,
    "capitalExpenditures": -12.715e9,
    "ebitda": 144.427e9,
    "totalDebt": 112.377e9,
    "totalCash": 54.697e9,
    "beta": 1.069,
    "sector": "Technology",
}
AAPL_REVENUE = [416.161e9, 391.035e9, 383.285e9, 394.328e9, 365.817e9]
MSFT = {
    "marketCap": 3.955e12,
    "freeCashflow": 66.987e9,
    "netIncomeToCommon": 133.749e9,
    "depreciation": 38.534e9,
    "capitalExpenditures": -115.948e9,
    "ebitda": 207.519e9,
    "totalDebt": 128.808e9,
    "totalCash": 76.843e9,
    "beta": 1.099,
    "sector": "Technology",
}
MSFT_REVENUE = [331.839e9, 281.724e9, 245.122e9, 211.915e9, 198.270e9]


@pytest.mark.unit
def test_dcf_value_matches_hand_calculation() -> None:
    flat = DcfScenario(growth_1=0.0, terminal_growth=0.0, wacc=0.10)
    # 10 years of 100 at 10% + a perpetuity of 1000 discounted 10 years — no haircut
    annuity = sum(100 / 1.1**t for t in range(1, 11))
    assert dcf_value(100, flat) == pytest.approx(annuity + 1000 / 1.1**10)


@pytest.mark.unit
def test_stage_two_fades_to_terminal_growth() -> None:
    fading = DcfScenario(growth_1=0.20, terminal_growth=0.0, wacc=0.10)
    flat_high = DcfScenario(growth_1=0.20, terminal_growth=0.20 - 1e-9, wacc=0.30)
    assert dcf_value(100, fading) < dcf_value(100, DcfScenario(0.20, 0.0, 0.10), 10, 0)
    assert dcf_value(100, flat_high) > 0
    assert dcf_value(100, DcfScenario(0.1, terminal_growth=0.1, wacc=0.1)) == 0.0
    assert dcf_value(-5, fading) == 0.0


@pytest.mark.unit
def test_discount_rate_is_capm_within_bounds() -> None:
    assert discount_rate({"beta": 1.0}) == pytest.approx(0.0925)
    assert discount_rate({}) == pytest.approx(0.0925)  # unknown beta → market
    assert discount_rate({"beta": 3.0}) == 0.13
    assert discount_rate({"beta": 0.2}) == 0.07


@pytest.mark.unit
def test_growth_comes_from_the_company_revenue() -> None:
    g = growth_estimate({}, AAPL_REVENUE)
    cagr = (416.161 / 365.817) ** 0.25 - 1
    assert g.rate == pytest.approx((cagr + 416.161 / 391.035 - 1) / 2)
    assert g.source == "revenue, 4-year history"
    assert growth_estimate({}, [300, 100]).rate == MAX_GROWTH  # 200% capped
    assert growth_estimate({}, [80, 100, 120]).rate == 0.0  # shrinking floored at 0
    assert growth_estimate({"revenueGrowth": 0.08}).rate == 0.08
    assert growth_estimate({}) == growth_estimate({}, [None, 0])  # no history
    assert growth_estimate({}).rate == DEFAULT_GROWTH


@pytest.mark.unit
def test_owner_earnings_count_only_maintenance_capex() -> None:
    # Capex above depreciation builds growth (an AI build-out), it is not lost cash
    assert owner_earnings(MSFT) == pytest.approx(133.749e9)
    assert owner_earnings({"netIncome": 100, "depreciation": 20, "capitalExpenditures": -10}) == 110
    assert owner_earnings({"netIncomeToCommon": -1}) is None
    assert normalized_cash_flow(MSFT) == (pytest.approx(133.749e9), "owner earnings")
    assert normalized_cash_flow({"freeCashflow": 5.0}) == (5.0, "free cash flow")
    assert normalized_cash_flow({"operatingIncome": 100}) == (75.0, "75% of operating income")
    assert normalized_cash_flow({}) == (0.0, "none")
    assert earnings_power_value({"netIncome": 90}, 0.09) == pytest.approx(1000)
    assert earnings_power_value({}, 0.09) is None


@pytest.mark.unit
def test_ev_ebitda() -> None:
    tech = {"ebitda": 100, "sector": "Technology", "totalDebt": 300, "totalCash": 50}
    assert ev_ebitda_value(tech) == 100 * 20 - 300 + 50
    assert ev_ebitda_value({"ebitda": 100, "sector": "Unknown"}) == 1200
    assert ev_ebitda_value({"ebitda": 0}) is None


@pytest.mark.unit
def test_scenarios_are_ordered() -> None:
    values = {n: dcf_value(1e9, sc) for n, sc in scenarios(0.10, 0.09).items()}
    assert values["bear"] < values["base"] < values["bull"]


@pytest.mark.unit
def test_reverse_dcf_finds_the_growth_priced_in() -> None:
    base = dcf_value(1e9, DcfScenario(0.12, 0.025, 0.09))
    assert implied_growth(base, 1e9, 0.09) == pytest.approx(0.12, abs=1e-6)
    assert implied_growth(0, 1e9, 0.09) is None
    assert implied_growth(1e9, 0, 0.09) is None
    assert implied_growth(1e20, 1e9, 0.09) is None  # beyond any plausible growth


@pytest.mark.unit
def test_live_calibration_tells_apple_from_microsoft() -> None:
    """
    With fixed 7% growth, a 15% haircut and 80% of all capex as maintenance, both
    came out ~-60% "overvalued". With their own numbers: Microsoft's growth and
    AI build-out make it about fair; Apple's price implies ~23% growth a year
    against ~5% of its own, which is a finding, not a calibration error.
    """
    msft = summarize(MSFT, MSFT_REVENUE)
    assert msft.signal == "neutral" and abs(msft.margin_of_safety) < 0.10
    assert msft.growth.rate == pytest.approx(0.158, abs=0.002)
    assert msft.implied_growth == pytest.approx(0.16, abs=0.01)

    aapl = summarize(AAPL, AAPL_REVENUE)
    assert aapl.signal == "bearish"
    assert -0.60 < aapl.margin_of_safety < -0.45
    assert aapl.implied_growth > 4 * aapl.growth.rate
    assert aapl.cash_flow_source == "owner earnings"
    assert aapl.earnings_power_value < aapl.dcf["bear"]  # no growth is worth the least


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
