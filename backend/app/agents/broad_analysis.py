"""BroadAnalysisAgent — business model and competitive position (FMP profile + 10-K Item 1)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent

_BUSINESS_CHARS = 8_000
_DESCRIPTION_CHARS = 1_500


class BroadAnalysisResult(AnalysisResult):
    company_name: str
    sector: str
    industry: str
    market_cap_b: float


@dataclass(frozen=True)
class BroadAnalysisData:
    profile: dict
    business_text: str
    info: dict


@register_agent(
    "broad_analysis",
    description="Business quality and competitive landscape (FMP + SEC 10-K)",
    recommendation_weight=10,
)
class BroadAnalysisAgent(Agent[BroadAnalysisData, BroadAnalysisResult]):
    result_model = BroadAnalysisResult

    async def fetch(self, symbol: str, run_date: date) -> BroadAnalysisData:
        profile, business_text, info = await asyncio.gather(
            self.ctx.fmp.get_company_profile(symbol),
            self.ctx.edgar.get_business_section(symbol),
            self.ctx.yfinance.get_info(symbol),
        )
        return BroadAnalysisData(profile=profile, business_text=business_text, info=info)

    async def analyze(
        self, symbol: str, data: BroadAnalysisData, memory: list[str]
    ) -> BroadAnalysisResult:
        p, info = data.profile, data.info
        name = p.get("companyName") or symbol
        sector = p.get("sector") or info.get("sector") or "Unknown"
        industry = p.get("industry") or info.get("industry") or "Unknown"
        market_cap_b = (p.get("mktCap") or info.get("marketCap") or 0) / 1e9

        judgement = await self.judge(
            f"""Symbol: {symbol} | Company: {name}
Sector: {sector} | Industry: {industry}
Market cap: ${market_cap_b:.1f}B | CEO: {p.get('ceo') or 'Unknown'} | \
Employees: {p.get('fullTimeEmployees') or 'Unknown'} | IPO: {p.get('ipoDate') or 'Unknown'}

Company description (FMP):
{(p.get('description') or '')[:_DESCRIPTION_CHARS]}

Business section from the latest 10-K (SEC EDGAR):
{data.business_text[:_BUSINESS_CHARS] or 'Not available'}

Knowledge base context:
{memory_block(memory)}""",
            fallback=neutral_fallback(),
        )
        return BroadAnalysisResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            company_name=name,
            sector=sector,
            industry=industry,
            market_cap_b=market_cap_b,
            summary=f"Broad analysis: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"— {judgement.reasoning}",
        )
