"""
Intrinsic value from the company's own numbers (Damodaran / Greenwald style):

  cash flow     owner earnings = net income + D&A − maintenance capex, where
                maintenance capex ≈ depreciation (capex above it builds growth —
                today's AI build-outs would otherwise read as lost cash); falls back
                to free cash flow, then 75% of operating income
  growth        years 1-5: the company's revenue growth (mean of the multi-year CAGR
                and the latest year), capped at 25%; years 6-10 fade to the
                terminal rate
  discount      CAPM cost of equity: risk-free + beta × equity risk premium, 7-13%
  methods       DCF (bear / base / bull around that growth and rate) and sector
                EV/EBITDA; the intrinsic value is their mean
  context       earnings power value (no growth at all) and the reverse DCF: the
                growth the market cap implies, to compare with the company's own

All values are equity values in USD, comparable with market cap. A missing
input is not a zero: it is reported, and the method that needs it is left out.
Conservatism lives in one place — the margin-of-safety threshold.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.signals import SignalLabel
from app.domain.stats import mean

MARGIN_OF_SAFETY_THRESHOLD = 0.20
RISK_FREE_RATE = 0.0425  # 10-year US Treasury, late 2026
EQUITY_RISK_PREMIUM = 0.05
_WACC_BOUNDS = (0.07, 0.13)
MAX_GROWTH = 0.25  # a 5-year rate a mega-cap can plausibly keep up
DEFAULT_GROWTH = 0.04  # ≈ nominal GDP, when there is no revenue history
TERMINAL_GROWTH = 0.025
_OPERATING_INCOME_CASH_SHARE = 0.75
_DEFAULT_EV_EBITDA_MULTIPLE = 12.0
_SECTOR_EV_EBITDA = {
    "technology": 20.0,
    "healthcare": 16.0,
    "consumer cyclical": 14.0,
    "financial services": 12.0,
    "communication services": 16.0,
    "industrials": 13.0,
    "consumer defensive": 14.0,
    "energy": 8.0,
    "utilities": 10.0,
    "real estate": 18.0,
    "basic materials": 10.0,
}


@dataclass(frozen=True)
class DcfScenario:
    growth_1: float  # years 1-5; years 6-10 fade linearly to terminal_growth
    terminal_growth: float
    wacc: float


@dataclass(frozen=True)
class Growth:
    rate: float
    source: str  # where the rate came from, for the prompt and the result


@dataclass(frozen=True)
class ValuationSummary:
    market_cap: float
    cash_flow: float  # the yearly cash the DCF starts from
    cash_flow_source: str
    growth: Growth
    discount_rate: float
    dcf: dict[str, float]
    earnings_power_value: float | None
    ev_ebitda_value: float | None
    avg_intrinsic_value: float
    margin_of_safety: float  # positive = undervalued
    implied_growth: float | None  # years 1-5 growth the market cap prices in
    signal: SignalLabel
    confidence: float


def discount_rate(info: dict) -> float:
    """CAPM cost of equity (beta 1 when unknown), kept within 7-13%."""
    beta = info.get("beta")
    beta = float(beta) if isinstance(beta, int | float) and beta > 0 else 1.0
    low, high = _WACC_BOUNDS
    return min(max(RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM, low), high)


def growth_estimate(info: dict, revenues: Sequence[float | None] = ()) -> Growth:
    """
    Years 1-5 growth from revenue, most recent year first: the mean of the
    multi-year CAGR and the latest year's growth, kept within 0-25%.
    """
    rev = [float(r) for r in revenues if isinstance(r, int | float) and r > 0]
    rates: list[float] = []
    if len(rev) >= 3:
        rates.append((rev[0] / rev[-1]) ** (1 / (len(rev) - 1)) - 1)
    if len(rev) >= 2:
        rates.append(rev[0] / rev[1] - 1)
        source = f"revenue, {len(rev) - 1}-year history"
    elif isinstance(info.get("revenueGrowth"), int | float):
        rates.append(float(info["revenueGrowth"]))
        source = "latest revenue growth"
    else:
        return Growth(DEFAULT_GROWTH, "no revenue history: default")
    return Growth(min(max(mean(rates), 0.0), MAX_GROWTH), source)


def owner_earnings(info: dict) -> float | None:
    """Net income + D&A − maintenance capex (≈ D&A, never more than the capex spent)."""
    net_income = info.get("netIncomeToCommon") or info.get("netIncome")
    if not isinstance(net_income, int | float) or net_income <= 0:
        return None
    depreciation = info.get("depreciation") or 0
    capex = info.get("capitalExpenditures")
    # Capex not reported: assume maintenance ≈ D&A, never add the D&A back unspent
    maintenance = depreciation if capex is None else min(abs(capex), depreciation)
    value = net_income + depreciation - maintenance
    return value if value > 0 else None


def normalized_cash_flow(info: dict) -> tuple[float, str]:
    """The cash the DCF starts from, and which figure it is (0 when none is positive)."""
    oe = owner_earnings(info)
    if oe:
        return oe, "owner earnings"
    fcf = info.get("freeCashflow") or 0
    if fcf > 0:
        return float(fcf), "free cash flow"
    operating = (info.get("operatingIncome") or 0) * _OPERATING_INCOME_CASH_SHARE
    if operating > 0:
        return operating, "75% of operating income"
    return 0.0, "none"


def scenarios(growth: float, wacc: float) -> dict[str, DcfScenario]:
    """Bear / base / bull around the company's own growth and discount rate."""
    return {
        "bear": DcfScenario(growth * 0.5, 0.020, wacc + 0.01),
        "base": DcfScenario(growth, TERMINAL_GROWTH, wacc),
        "bull": DcfScenario(min(growth * 1.4, 0.30), 0.030, wacc - 0.005),
    }


def dcf_value(cash_flow: float, scenario: DcfScenario, years_1: int = 5, years_2: int = 5) -> float:
    """Two-stage DCF (stage 2 fades to terminal growth) plus a Gordon terminal value."""
    if scenario.wacc <= scenario.terminal_growth or cash_flow <= 0:
        return 0.0
    pv, cf = 0.0, cash_flow
    for t in range(1, years_1 + years_2 + 1):
        fade = (t - years_1) / years_2 if t > years_1 else 0.0
        cf *= 1 + scenario.growth_1 + (scenario.terminal_growth - scenario.growth_1) * fade
        pv += cf / (1 + scenario.wacc) ** t
    terminal = cf * (1 + scenario.terminal_growth) / (scenario.wacc - scenario.terminal_growth)
    return pv + terminal / (1 + scenario.wacc) ** (years_1 + years_2)


def implied_growth(market_cap: float, cash_flow: float, wacc: float) -> float | None:
    """Reverse DCF: the years 1-5 growth at which the base DCF equals the market cap."""
    if market_cap <= 0 or cash_flow <= 0 or wacc <= TERMINAL_GROWTH:
        return None
    low, high = -0.5, 1.5
    if not dcf_value(cash_flow, DcfScenario(low, TERMINAL_GROWTH, wacc)) <= market_cap:
        return None  # cheaper than even a shrinking business
    if dcf_value(cash_flow, DcfScenario(high, TERMINAL_GROWTH, wacc)) < market_cap:
        return None  # beyond any plausible growth
    for _ in range(60):
        mid = (low + high) / 2
        if dcf_value(cash_flow, DcfScenario(mid, TERMINAL_GROWTH, wacc)) < market_cap:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def earnings_power_value(info: dict, wacc: float) -> float | None:
    """Owner earnings / discount rate: what the business is worth with no growth at all."""
    oe = owner_earnings(info)
    return oe / wacc if oe else None


def ev_ebitda_value(info: dict) -> float | None:
    """
    EBITDA × sector multiple − debt + cash. None when EBITDA is not positive, or debt is
    not reported: an enterprise value can't be turned into equity without it, and
    reading it as 0 would overstate the equity. Missing cash only understates it.
    """
    ebitda = info.get("ebitda") or 0
    if ebitda <= 0 or info.get("totalDebt") is None:
        return None
    multiple = _SECTOR_EV_EBITDA.get(
        (info.get("sector") or "").lower(), _DEFAULT_EV_EBITDA_MULTIPLE
    )
    equity = ebitda * multiple - (info.get("totalDebt") or 0) + (info.get("totalCash") or 0)
    return max(equity, 0.0)


def summarize(info: dict, revenues: Sequence[float | None] = ()) -> ValuationSummary:
    """revenues: annual revenue, most recent first (FMP income statements)."""
    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0.0
    shares = info.get("sharesOutstanding") or 0
    # 0.0 = unknown. (It used to fall back to price × 1 share, which made any
    # intrinsic value look like an enormous margin of safety.)
    market_cap = info.get("marketCap") or price * shares

    growth = growth_estimate(info, revenues)
    wacc = discount_rate(info)
    cash_flow, cash_source = normalized_cash_flow(info)
    dcf = {name: dcf_value(cash_flow, sc) for name, sc in scenarios(growth.rate, wacc).items()}
    ev_value = ev_ebitda_value(info)
    estimates = [v for v in (dcf["base"], ev_value) if v and v > 0]
    intrinsic = mean(estimates)

    mos = (intrinsic - market_cap) / market_cap if intrinsic > 0 and market_cap > 0 else 0.0
    if intrinsic <= 0 or market_cap <= 0:  # nothing to compare: no evidence either way
        signal, confidence = "neutral", 0.0
    elif mos > MARGIN_OF_SAFETY_THRESHOLD:
        signal: SignalLabel = "bullish"
        confidence = min(mos * 200, 90.0)
    elif mos < -MARGIN_OF_SAFETY_THRESHOLD:
        signal = "bearish"
        confidence = min(abs(mos) * 200, 90.0)
    else:
        signal, confidence = "neutral", 50.0

    return ValuationSummary(
        market_cap=market_cap,
        cash_flow=cash_flow,
        cash_flow_source=cash_source,
        growth=growth,
        discount_rate=wacc,
        dcf=dcf,
        earnings_power_value=earnings_power_value(info, wacc),
        ev_ebitda_value=ev_value,
        avg_intrinsic_value=intrinsic,
        margin_of_safety=mos,
        implied_growth=implied_growth(market_cap, cash_flow, wacc),
        signal=signal,
        confidence=confidence,
    )


def with_fmp_fallbacks(info: dict, cash_flow_rows: list[dict], profile: dict) -> dict:
    """
    Fill what yfinance didn't return from FMP: the latest freeCashFlow and the
    market cap (yfinance's info can come back with only a quote — see
    providers/yahoo_chart.py — and without a market cap there is no valuation).
    """
    filled = dict(info)
    fmp_fcf = cash_flow_rows[0].get("freeCashFlow") if cash_flow_rows else None
    if not filled.get("freeCashflow") and fmp_fcf:
        filled["freeCashflow"] = fmp_fcf
    if not filled.get("marketCap") and profile.get("marketCap"):
        filled["marketCap"] = profile["marketCap"]
    return filled
