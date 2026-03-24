"""
ValuationAgent — multi-method intrinsic value analysis.
Adapted from virattt/ai-hedge-fund valuation.py + anthropics/financial-services-plugins DCF framework.

Methods:
  1. DCF (Bear/Base/Bull scenarios) — discounted cash flow
  2. Owner Earnings (Buffett-style) — NI + D&A - maintenance capex
  3. EV/EBITDA multiple — market comparison

Signal: bullish if intrinsic value > market price by >20% margin of safety,
        bearish if market price > intrinsic value by >20%.
"""
from __future__ import annotations

import logging
import math

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import fmp_service as fmp_svc
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a quantitative valuation analyst. You receive intrinsic value estimates
from multiple methods and the current market price.
Return JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (string, max 200 chars).
Be conservative — only signal bullish if there is clear margin of safety (>20%).
"""


class ValuationAgent(AgentBase):
    agent_type = "valuation"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        info, history, fmp_metrics, fmp_cashflow = await asyncio.gather(
            yf_svc.get_info(symbol),
            yf_svc.get_history(symbol, period="2y"),
            fmp_svc.get_key_metrics(symbol, limit=1),
            fmp_svc.get_cash_flow_statements(symbol, limit=3),
        )
        return {
            "symbol": symbol,
            "info": info,
            "history": history,
            "fmp_metrics": fmp_metrics,
            "fmp_cashflow": fmp_cashflow,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        info = data["info"]
        symbol = data["symbol"]
        fmp_metrics = data.get("fmp_metrics") or []
        fmp_cashflow = data.get("fmp_cashflow") or []

        # Use FMP FCF as fallback when yfinance freeCashflow is None
        if not info.get("freeCashflow") and fmp_cashflow:
            fmp_fcf = fmp_cashflow[0].get("freeCashFlow")
            if fmp_fcf:
                info = {**info, "freeCashflow": fmp_fcf}

        price = info.get("regularMarketPrice") or info.get("currentPrice") or 0.0
        shares = info.get("sharesOutstanding") or 1
        market_cap = info.get("marketCap") or (price * shares)

        # Method 1: DCF (three scenarios)
        dcf = _dcf_scenarios(info, market_cap)

        # Method 2: Owner Earnings
        oe_value = _owner_earnings_valuation(info)

        # Method 3: EV/EBITDA
        ev_ebitda_value = _ev_ebitda_valuation(info)

        # Average available estimates (filter None)
        estimates = [v for v in [dcf["base"], oe_value, ev_ebitda_value] if v and v > 0]
        avg_intrinsic = sum(estimates) / len(estimates) if estimates else 0.0

        # Signal based on margin of safety
        if avg_intrinsic > 0 and market_cap > 0:
            mos = (avg_intrinsic - market_cap) / market_cap  # positive = undervalued
        else:
            mos = 0.0

        if mos > 0.20:
            base_signal = "bullish"
            base_conf = min(mos * 200, 90.0)
        elif mos < -0.20:
            base_signal = "bearish"
            base_conf = min(abs(mos) * 200, 90.0)
        else:
            base_signal = "neutral"
            base_conf = 50.0

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        mktcap_b = market_cap / 1e9
        intrinsic_b = avg_intrinsic / 1e9
        user_prompt = f"""
Symbol: {symbol}
Current market cap: ${mktcap_b:.2f}B

Intrinsic value estimates:
  DCF Bear:  ${dcf['bear'] / 1e9:.2f}B  (conservative: low growth, high WACC)
  DCF Base:  ${dcf['base'] / 1e9:.2f}B  (consensus assumptions)
  DCF Bull:  ${dcf['bull'] / 1e9:.2f}B  (optimistic: high growth, expanding margins)
  Owner Earnings: ${(oe_value or 0) / 1e9:.2f}B
  EV/EBITDA Method: ${(ev_ebitda_value or 0) / 1e9:.2f}B

Average intrinsic value: ${intrinsic_b:.2f}B
Margin of safety: {mos:+.1%}  (positive = undervalued, negative = overvalued)
Base signal: {base_signal} ({base_conf:.0f}%)

Prior knowledge base context: {context_str}

Produce final signal JSON.
"""
        result = await llm_service.call_claude(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AnalystSignal,
        )

        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "dcf": dcf,
            "owner_earnings_value": oe_value,
            "ev_ebitda_value": ev_ebitda_value,
            "avg_intrinsic_value": avg_intrinsic,
            "margin_of_safety": mos,
            "market_cap": market_cap,
            "summary": f"Valuation: {result.signal} ({result.confidence:.0f}%) MoS={mos:+.1%} — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }


# ---------------------------------------------------------------------------
# Valuation calculation functions
# ---------------------------------------------------------------------------

def _dcf_scenarios(info: dict, market_cap: float) -> dict[str, float]:
    """
    Three-scenario DCF using FCF as base.
    Bear/Base/Bull per anthropics/financial-services-plugins DCF framework.
    Returns dict of {bear, base, bull} market cap equivalents.
    """
    fcf = info.get("freeCashflow") or 0
    if fcf <= 0:
        # Fallback: use operating income × (1 - tax rate)
        op_income = info.get("operatingIncome") or 0
        fcf = op_income * 0.75

    if fcf <= 0:
        return {"bear": 0.0, "base": 0.0, "bull": 0.0}

    scenarios = {
        "bear": {"growth_1": 0.03, "growth_2": 0.02, "terminal_g": 0.020, "wacc": 0.12},
        "base": {"growth_1": 0.07, "growth_2": 0.04, "terminal_g": 0.025, "wacc": 0.10},
        "bull": {"growth_1": 0.12, "growth_2": 0.06, "terminal_g": 0.030, "wacc": 0.09},
    }

    results = {}
    for name, params in scenarios.items():
        pv = _dcf_value(
            fcf=fcf,
            growth_rate_1=params["growth_1"],
            growth_rate_2=params["growth_2"],
            terminal_growth=params["terminal_g"],
            wacc=params["wacc"],
            years_1=5,
            years_2=5,
        )
        results[name] = pv

    return results


def _dcf_value(
    fcf: float,
    growth_rate_1: float,
    growth_rate_2: float,
    terminal_growth: float,
    wacc: float,
    years_1: int = 5,
    years_2: int = 5,
) -> float:
    """
    Two-stage DCF: explicit forecast + terminal value.
    Returns present value of all future cash flows.
    """
    if wacc <= terminal_growth:
        return 0.0

    pv = 0.0
    cf = fcf

    # Stage 1: explicit growth period
    for t in range(1, years_1 + 1):
        cf *= (1 + growth_rate_1)
        pv += cf / (1 + wacc) ** t

    # Stage 2: fade-down growth period
    for t in range(years_1 + 1, years_1 + years_2 + 1):
        cf *= (1 + growth_rate_2)
        pv += cf / (1 + wacc) ** t

    # Terminal value (Gordon Growth)
    terminal_cf = cf * (1 + terminal_growth)
    terminal_value = terminal_cf / (wacc - terminal_growth)
    pv += terminal_value / (1 + wacc) ** (years_1 + years_2)

    # 15% haircut for margin of safety
    return pv * 0.85


def _owner_earnings_valuation(info: dict) -> float | None:
    """
    Buffett-style Owner Earnings: NI + D&A - maintenance capex.
    Applies 12x multiple to normalized owner earnings.
    """
    net_income = info.get("netIncomeToCommon") or info.get("netIncome") or 0
    depreciation = info.get("depreciation") or 0
    capex = abs(info.get("capitalExpenditures") or 0)

    if net_income <= 0:
        return None

    # Maintenance capex ≈ 80% of total capex (rough estimate)
    maintenance_capex = capex * 0.80
    owner_earnings = net_income + depreciation - maintenance_capex

    if owner_earnings <= 0:
        return None

    # Apply multiple (12x base, typical for moderate-quality business)
    return owner_earnings * 12.0


def _ev_ebitda_valuation(info: dict) -> float | None:
    """
    EV/EBITDA approach: apply sector median multiple to EBITDA.
    Returns implied market cap.
    """
    ebitda = info.get("ebitda") or 0
    total_debt = info.get("totalDebt") or 0
    cash = info.get("totalCash") or 0

    if ebitda <= 0:
        return None

    # Sector-appropriate multiple (conservative default = 12x)
    sector = (info.get("sector") or "").lower()
    multiple = {
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
    }.get(sector, 12.0)

    implied_ev = ebitda * multiple
    implied_equity = implied_ev - total_debt + cash
    return max(implied_equity, 0)
