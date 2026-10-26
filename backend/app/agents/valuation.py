"""ValuationAgent — DCF (bear/base/bull), owner earnings and EV/EBITDA vs market cap."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import billions, knowledge_block
from app.agents.registry import register_agent
from app.domain.valuation import (
    MARGIN_OF_SAFETY_THRESHOLD,
    ValuationSummary,
    summarize,
    with_fmp_fallbacks,
)


class ValuationResult(AnalysisResult):
    dcf: dict[str, float]
    owner_earnings_value: float | None
    ev_ebitda_value: float | None
    avg_intrinsic_value: float
    margin_of_safety: float
    market_cap: float


@dataclass(frozen=True)
class ValuationData:
    info: dict
    fmp_cash_flow: list[dict]
    fmp_profile: dict


def _signal_matches_margin_of_safety(data: object, result: "ValuationResult") -> str | None:
    """The prompt's rule: bullish only with a clear margin of safety, bearish when overvalued."""
    if result.avg_intrinsic_value <= 0:
        return None  # nothing to compare against — covered by data gaps
    mos = result.margin_of_safety
    if result.signal == "bullish" and mos <= MARGIN_OF_SAFETY_THRESHOLD:
        return f"bullish with a margin of safety of {mos:+.0%} (rule: > +20%)"
    if result.signal == "bearish" and mos > 0:
        return f"bearish although intrinsic value is above market cap (margin {mos:+.0%})"
    return None


@register_agent(
    "valuation",
    description="Multi-method intrinsic value and margin of safety",
    recommendation_weight=20,
    company_only=True,
    invariants=(_signal_matches_margin_of_safety,),
)
class ValuationAgent(Agent[ValuationData, ValuationResult]):
    result_model = ValuationResult

    async def fetch(self, symbol: str, run_date: date) -> ValuationData:
        info, cash_flow, profile = await asyncio.gather(
            self.ctx.yfinance.get_info(symbol),
            self.ctx.fmp.get_cash_flow_statements(symbol, limit=3),
            self.ctx.fmp.get_company_profile(symbol),  # cached: broad_analysis asks too
        )
        return ValuationData(info=info, fmp_cash_flow=cash_flow, fmp_profile=profile)

    async def analyze(self, symbol: str, data: ValuationData, memory: list[str]) -> ValuationResult:
        v = summarize(with_fmp_fallbacks(data.info, data.fmp_cash_flow, data.fmp_profile))
        judgement = await self.judge(
            _prompt(symbol, v, memory),
            fallback=quant_fallback(v.signal, v.confidence, "margin-of-safety rule"),
        )
        return ValuationResult.from_judgement(
            "Valuation",
            judgement,
            detail=f"MoS={v.margin_of_safety:+.1%}",
            dcf=v.dcf,
            owner_earnings_value=v.owner_earnings_value,
            ev_ebitda_value=v.ev_ebitda_value,
            avg_intrinsic_value=v.avg_intrinsic_value,
            margin_of_safety=v.margin_of_safety,
            market_cap=v.market_cap,
        )


def _prompt(symbol: str, v: ValuationSummary, memory: list[str]) -> str:
    return f"""Symbol: {symbol}
Current market cap: {billions(v.market_cap or None)}

Intrinsic value estimates:
  DCF bear: {billions(v.dcf['bear'])}  (low growth, high WACC)
  DCF base: {billions(v.dcf['base'])}  (consensus assumptions)
  DCF bull: {billions(v.dcf['bull'])}  (high growth, expanding margins)
  Owner earnings: {billions(v.owner_earnings_value)}
  EV/EBITDA method: {billions(v.ev_ebitda_value)}

Average intrinsic value: {billions(v.avg_intrinsic_value)}
Margin of safety: {v.margin_of_safety:+.1%} (positive = undervalued)
Rule-based signal: {v.signal} ({v.confidence:.0f}%)

{knowledge_block(memory)}"""
