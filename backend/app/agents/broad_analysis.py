"""BroadAnalysisAgent — business model and competitive position (FMP profile + 10-K Item 1)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent

# The opening of the Business section is its overview; moat and risk read the rest
# (was 8,000 chars — the same text moat also receives)
_BUSINESS_CHARS = 4_000
_DESCRIPTION_CHARS = 1_500


class BroadAnalysisResult(AnalysisResult):
    company_name: str
    sector: str
    industry: str
    market_cap_b: float | None  # None: not reported (e.g. withheld in a historical run)


@dataclass(frozen=True)
class BroadAnalysisData:
    profile: dict
    business_text: str
    info: dict


@register_agent(
    "broad_analysis",
    description="Business quality and competitive landscape (FMP + SEC 10-K)",
    recommendation_weight=10,
    company_only=True,
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
        cap = p.get("marketCap") or info.get("marketCap")
        market_cap_b = cap / 1e9 if isinstance(cap, int | float) and cap > 0 else None
        cap_text = "N/A" if market_cap_b is None else f"${market_cap_b:.1f}B"

        judgement = await self.judge(
            f"""Symbol: {symbol} | Company: {name}
Sector: {sector} | Industry: {industry}
Market cap: {cap_text} | CEO: {p.get('ceo') or 'Unknown'} | \
Employees: {p.get('fullTimeEmployees') or 'Unknown'} | IPO: {p.get('ipoDate') or 'Unknown'}

Company description (FMP):
{(p.get('description') or '')[:_DESCRIPTION_CHARS]}

Business section from the latest 10-K (SEC EDGAR):
{data.business_text[:_BUSINESS_CHARS] or 'Not available'}

{knowledge_block(memory)}""",
            fallback=neutral_fallback(),
        )
        return BroadAnalysisResult.from_judgement(
            "Broad analysis",
            judgement,
            company_name=name,
            sector=sector,
            industry=industry,
            market_cap_b=market_cap_b,
        )
