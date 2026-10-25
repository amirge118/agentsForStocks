"""MoatAgent — economic moat from 10-K text, margin durability and intangibles (EDGAR + FMP)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent
from app.domain.financials import MOAT_KEYWORDS, MarginProfile, margin_profile
from app.domain.stats import find_keywords
from app.knowledge.store import Learning

_BUSINESS_CHARS = 6_000


class MoatResult(AnalysisResult):
    avg_gross_margin: float
    gross_margin_variance: float
    intangibles_pct: float
    moat_keywords: list[str]


@dataclass(frozen=True)
class MoatData:
    business_text: str
    ratios: list[dict]
    balance: list[dict]
    profile: dict


@register_agent(
    "moat",
    description="Competitive advantage: brand, IP, switching costs, margin durability",
    recommendation_weight=15,
)
class MoatAgent(Agent[MoatData, MoatResult]):
    result_model = MoatResult

    async def fetch(self, symbol: str, run_date: date) -> MoatData:
        business_text, ratios, balance, profile = await asyncio.gather(
            self.ctx.edgar.get_business_section(symbol),
            self.ctx.fmp.get_financial_ratios(symbol, limit=5),
            self.ctx.fmp.get_balance_sheets(symbol, limit=3),
            self.ctx.fmp.get_company_profile(symbol),
        )
        return MoatData(business_text, ratios, balance, profile)

    async def analyze(self, symbol: str, data: MoatData, memory: list[str]) -> MoatResult:
        keywords = find_keywords(data.business_text, MOAT_KEYWORDS)
        margins = margin_profile(data.ratios, data.balance)
        judgement = await self.judge(
            _prompt(symbol, data, keywords, margins, memory), fallback=neutral_fallback()
        )
        return MoatResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            avg_gross_margin=margins.avg_gross_margin,
            gross_margin_variance=margins.gross_margin_variance,
            intangibles_pct=margins.intangibles_pct,
            moat_keywords=keywords,
            summary=f"Moat: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"— {judgement.reasoning}",
        )

    def learnings(self, symbol: str, result: MoatResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        if result.moat_keywords and result.signal == "bullish":
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Moat indicators detected: {', '.join(result.moat_keywords[:5])}",
                    tags=("moat", "competitive_advantage"),
                )
            )
        return learnings


def _prompt(
    symbol: str, d: MoatData, keywords: list[str], m: MarginProfile, memory: list[str]
) -> str:
    return f"""Symbol: {symbol} | Industry: {d.profile.get('industry') or 'Unknown'}

Moat keywords found in the 10-K: {', '.join(keywords) or 'none detected'}
Gross margin (5-year average): {m.avg_gross_margin * 100:.1f}%
Gross margin variance (lower = more pricing power): {m.gross_margin_variance * 100:.2f}%
Intangibles / total assets: {m.intangibles_pct * 100:.1f}%

10-K Business section (excerpt):
{d.business_text[:_BUSINESS_CHARS] or 'Not available'}

Knowledge base context:
{memory_block(memory)}"""
