"""ValuationAgent — DCF (bear/base/bull), owner earnings and EV/EBITDA vs market cap."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import billions, memory_block
from app.agents.registry import register_agent
from app.domain.valuation import ValuationSummary, summarize, with_fcf_fallback


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


@register_agent(
    "valuation",
    description="Multi-method intrinsic value and margin of safety",
    recommendation_weight=20,
)
class ValuationAgent(Agent[ValuationData, ValuationResult]):
    result_model = ValuationResult

    async def fetch(self, symbol: str, run_date: date) -> ValuationData:
        info, cash_flow = await asyncio.gather(
            self.ctx.yfinance.get_info(symbol),
            self.ctx.fmp.get_cash_flow_statements(symbol, limit=3),
        )
        return ValuationData(info=info, fmp_cash_flow=cash_flow)

    async def analyze(self, symbol: str, data: ValuationData, memory: list[str]) -> ValuationResult:
        v = summarize(with_fcf_fallback(data.info, data.fmp_cash_flow))
        judgement = await self.judge(
            _prompt(symbol, v, memory),
            fallback=quant_fallback(v.signal, v.confidence, "margin-of-safety rule"),
        )
        return ValuationResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            dcf=v.dcf,
            owner_earnings_value=v.owner_earnings_value,
            ev_ebitda_value=v.ev_ebitda_value,
            avg_intrinsic_value=v.avg_intrinsic_value,
            margin_of_safety=v.margin_of_safety,
            market_cap=v.market_cap,
            summary=f"Valuation: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"MoS={v.margin_of_safety:+.1%} — {judgement.reasoning}",
        )


def _prompt(symbol: str, v: ValuationSummary, memory: list[str]) -> str:
    return f"""Symbol: {symbol}
Current market cap: {billions(v.market_cap)}

Intrinsic value estimates:
  DCF bear: {billions(v.dcf['bear'])}  (low growth, high WACC)
  DCF base: {billions(v.dcf['base'])}  (consensus assumptions)
  DCF bull: {billions(v.dcf['bull'])}  (high growth, expanding margins)
  Owner earnings: {billions(v.owner_earnings_value)}
  EV/EBITDA method: {billions(v.ev_ebitda_value)}

Average intrinsic value: {billions(v.avg_intrinsic_value)}
Margin of safety: {v.margin_of_safety:+.1%} (positive = undervalued)
Rule-based signal: {v.signal} ({v.confidence:.0f}%)

Knowledge base context:
{memory_block(memory)}"""
