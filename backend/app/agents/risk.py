"""RiskAgent — 10-K risk factors, leverage, liquidity and market risk (EDGAR + FMP + yfinance)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent
from app.domain.financials import HIGH_RISK_KEYWORDS, liquidity_trend
from app.domain.stats import find_keywords
from app.knowledge.store import Learning

_RISK_TEXT_CHARS = 8_000


class RiskResult(AnalysisResult):
    debt_to_equity: float
    current_ratio: float
    beta: float
    risk_keywords: list[str]


@dataclass(frozen=True)
class RiskData:
    risk_text: str
    balance: list[dict]
    key_metrics: list[dict]
    info: dict


@register_agent(
    "risk",
    description="Downside risk: risk factors, leverage, liquidity, beta",
    recommendation_weight=15,
)
class RiskAgent(Agent[RiskData, RiskResult]):
    result_model = RiskResult

    async def fetch(self, symbol: str, run_date: date) -> RiskData:
        risk_text, balance, key_metrics, info = await asyncio.gather(
            self.ctx.edgar.get_risk_factors(symbol),
            self.ctx.fmp.get_balance_sheets(symbol, limit=3),
            self.ctx.fmp.get_key_metrics(symbol, limit=1),
            self.ctx.yfinance.get_info(symbol),
        )
        return RiskData(risk_text, balance, key_metrics, info)

    async def analyze(self, symbol: str, data: RiskData, memory: list[str]) -> RiskResult:
        km = data.key_metrics[0] if data.key_metrics else {}
        debt_to_equity = float(km.get("debtToEquity") or data.info.get("debtToEquity") or 0.0)
        current_ratio = float(km.get("currentRatio") or data.info.get("currentRatio") or 0.0)
        beta = float(data.info.get("beta") or 1.0)
        short_ratio = float(data.info.get("shortRatio") or 0.0)
        keywords = find_keywords(data.risk_text, HIGH_RISK_KEYWORDS)

        judgement = await self.judge(
            f"""Symbol: {symbol}

Financial risk metrics:
  Debt/equity:   {debt_to_equity:.2f}
  Current ratio: {current_ratio:.2f} (> 1.5 healthy, < 1.0 stress)
  Beta:          {beta:.2f}
  Short ratio:   {short_ratio:.1f} days
  Liquidity:     {liquidity_trend(data.balance)}

High-risk phrases in Risk Factors: {', '.join(keywords) or 'none'}

10-K Risk Factors (Item 1A):
{data.risk_text[:_RISK_TEXT_CHARS] or 'Not available'}

Knowledge base context:
{memory_block(memory)}

Bearish = high risk, bullish = low risk.""",
            fallback=neutral_fallback(),
        )
        return RiskResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            beta=beta,
            risk_keywords=keywords,
            summary=f"Risk: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"D/E={debt_to_equity:.1f} — {judgement.reasoning}",
        )

    def learnings(self, symbol: str, result: RiskResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        if result.risk_keywords:
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Risk factors flagged: {', '.join(result.risk_keywords[:5])}",
                    tags=("risk", "downside"),
                )
            )
        return learnings
