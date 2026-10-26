"""
Intrinsic value estimates (ai-hedge-fund valuation.py + Anthropic DCF framework):
three-scenario DCF, Buffett owner earnings, and sector EV/EBITDA multiples.
All values are equity values in USD, comparable with market cap.
"""

from dataclasses import dataclass

from app.domain.signals import SignalLabel
from app.domain.stats import mean

MARGIN_OF_SAFETY_THRESHOLD = 0.20
_DCF_HAIRCUT = 0.85  # 15% haircut on every DCF result
_OWNER_EARNINGS_MULTIPLE = 12.0
_MAINTENANCE_CAPEX_SHARE = 0.80
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
    growth_1: float  # years 1-5
    growth_2: float  # years 6-10
    terminal_growth: float
    wacc: float


DCF_SCENARIOS: dict[str, DcfScenario] = {
    "bear": DcfScenario(growth_1=0.03, growth_2=0.02, terminal_growth=0.020, wacc=0.12),
    "base": DcfScenario(growth_1=0.07, growth_2=0.04, terminal_growth=0.025, wacc=0.10),
    "bull": DcfScenario(growth_1=0.12, growth_2=0.06, terminal_growth=0.030, wacc=0.09),
}


@dataclass(frozen=True)
class ValuationSummary:
    market_cap: float
    dcf: dict[str, float]
    owner_earnings_value: float | None
    ev_ebitda_value: float | None
    avg_intrinsic_value: float
    margin_of_safety: float  # positive = undervalued
    signal: SignalLabel
    confidence: float


def dcf_value(fcf: float, scenario: DcfScenario, years_1: int = 5, years_2: int = 5) -> float:
    """Two-stage DCF with a Gordon-growth terminal value, after the 15% haircut."""
    if scenario.wacc <= scenario.terminal_growth:
        return 0.0
    pv = 0.0
    cf = fcf
    for t in range(1, years_1 + years_2 + 1):
        cf *= 1 + (scenario.growth_1 if t <= years_1 else scenario.growth_2)
        pv += cf / (1 + scenario.wacc) ** t
    terminal = cf * (1 + scenario.terminal_growth) / (scenario.wacc - scenario.terminal_growth)
    pv += terminal / (1 + scenario.wacc) ** (years_1 + years_2)
    return pv * _DCF_HAIRCUT


def dcf_scenarios(info: dict) -> dict[str, float]:
    """Bear/base/bull DCF from free cash flow (fallback: operating income × 0.75)."""
    fcf = info.get("freeCashflow") or 0
    if fcf <= 0:
        fcf = (info.get("operatingIncome") or 0) * 0.75
    if fcf <= 0:
        return {name: 0.0 for name in DCF_SCENARIOS}
    return {name: dcf_value(fcf, scenario) for name, scenario in DCF_SCENARIOS.items()}


def owner_earnings_value(info: dict) -> float | None:
    """(Net income + D&A − 80% of capex) × 12. None when earnings are not positive."""
    net_income = info.get("netIncomeToCommon") or info.get("netIncome") or 0
    if net_income <= 0:
        return None
    depreciation = info.get("depreciation") or 0
    capex = abs(info.get("capitalExpenditures") or 0)
    owner_earnings = net_income + depreciation - capex * _MAINTENANCE_CAPEX_SHARE
    return owner_earnings * _OWNER_EARNINGS_MULTIPLE if owner_earnings > 0 else None


def ev_ebitda_value(info: dict) -> float | None:
    """EBITDA × sector multiple − debt + cash. None when EBITDA is not positive."""
    ebitda = info.get("ebitda") or 0
    if ebitda <= 0:
        return None
    multiple = _SECTOR_EV_EBITDA.get(
        (info.get("sector") or "").lower(), _DEFAULT_EV_EBITDA_MULTIPLE
    )
    equity = ebitda * multiple - (info.get("totalDebt") or 0) + (info.get("totalCash") or 0)
    return max(equity, 0.0)


def summarize(info: dict) -> ValuationSummary:
    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0.0
    shares = info.get("sharesOutstanding") or 0
    # 0.0 = unknown. (It used to fall back to price × 1 share, which made any
    # intrinsic value look like an enormous margin of safety.)
    market_cap = info.get("marketCap") or price * shares

    dcf = dcf_scenarios(info)
    oe_value = owner_earnings_value(info)
    ev_value = ev_ebitda_value(info)
    estimates = [v for v in (dcf["base"], oe_value, ev_value) if v and v > 0]
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
        dcf=dcf,
        owner_earnings_value=oe_value,
        ev_ebitda_value=ev_value,
        avg_intrinsic_value=intrinsic,
        margin_of_safety=mos,
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
