"""RiskAgent — 10-K risk factors, leverage, liquidity and market risk (EDGAR + FMP + yfinance)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent
from app.domain.financials import HIGH_RISK_KEYWORDS, liquidity_trend
from app.domain.stats import find_keywords, relevant_excerpt
from app.knowledge.store import Learning

# The opening plus the sentences with high-risk phrases (was: the first 8,000 chars)
_RISK_TEXT_CHARS = 4_500


class RiskResult(AnalysisResult):
    debt_to_equity: float
    current_ratio: float
    beta: float
    risk_keywords: list[str]


@dataclass(frozen=True)
class RiskData:
    risk_text: str
    balance: list[dict]
    ratios: list[dict]
    info: dict


@register_agent(
    "risk",
    description="Downside risk: risk factors, leverage, liquidity, beta",
    recommendation_weight=15,
    company_only=True,
)
class RiskAgent(Agent[RiskData, RiskResult]):
    result_model = RiskResult

    async def fetch(self, symbol: str, run_date: date) -> RiskData:
        risk_text, balance, ratios, info = await asyncio.gather(
            self.ctx.edgar.get_risk_factors(symbol),
            self.ctx.fmp.get_balance_sheets(symbol, limit=3),
            self.ctx.fmp.get_financial_ratios(symbol, limit=1),
            self.ctx.yfinance.get_info(symbol),
        )
        return RiskData(risk_text, balance, ratios, info)

    async def analyze(self, symbol: str, data: RiskData, memory: list[str]) -> RiskResult:
        latest = data.ratios[0] if data.ratios else {}
        # FMP gives D/E as a ratio (1.5); yfinance gives it in percent (150)
        yf_de = data.info.get("debtToEquity")
        debt_to_equity = float(
            latest.get("debtToEquityRatio") or (yf_de / 100 if yf_de else 0.0) or 0.0
        )
        current_ratio = float(latest.get("currentRatio") or data.info.get("currentRatio") or 0.0)
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
{relevant_excerpt(data.risk_text, HIGH_RISK_KEYWORDS, _RISK_TEXT_CHARS) or 'Not available'}

{knowledge_block(memory)}

Bearish = high risk, bullish = low risk.""",
            fallback=neutral_fallback(),
        )
        return RiskResult.from_judgement(
            "Risk",
            judgement,
            detail=f"D/E={debt_to_equity:.1f}",
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            beta=beta,
            risk_keywords=keywords,
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
