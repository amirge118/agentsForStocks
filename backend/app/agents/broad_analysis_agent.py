"""
BroadAnalysisAgent — business model and competitive landscape overview.
Level 1 of the 10-level stock analysis framework.

Data sources:
  - FMP company profile (sector, description, CEO, market cap)
  - SEC EDGAR 10-K Item 1 (Business section — up to 8,000 chars)
  - yfinance info (price context)
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import edgar_service as edgar_svc
from app.services import fmp_service as fmp_svc
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior equity analyst assessing a company's business quality and competitive position.
Analyze the provided company description and 10-K business section.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars summarizing the key business quality insight).
Bullish = clear competitive moat, growing addressable market, strong management.
Bearish = commoditized business, declining relevance, weak positioning.
"""


class BroadAnalysisAgent(AgentBase):
    agent_type = "broad_analysis"

    async def fetch_data(self, symbol: str) -> dict:
        profile, business_text, info = await _fetch_all(symbol)
        return {
            "symbol": symbol,
            "profile": profile,
            "business_text": business_text[:8000],  # limit for LLM context
            "info": info,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        profile = data["profile"]
        business_text = data["business_text"]
        info = data["info"]

        company_name = profile.get("companyName") or symbol
        description = profile.get("description") or ""
        sector = profile.get("sector") or info.get("sector") or "Unknown"
        industry = profile.get("industry") or info.get("industry") or "Unknown"
        ceo = profile.get("ceo") or "Unknown"
        employees = profile.get("fullTimeEmployees") or 0
        ipo_date = profile.get("ipoDate") or "Unknown"
        mkt_cap_b = (profile.get("mktCap") or info.get("marketCap") or 0) / 1e9

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}  |  Company: {company_name}
Sector: {sector}  |  Industry: {industry}
Market Cap: ${mkt_cap_b:.1f}B  |  CEO: {ceo}  |  Employees: {employees:,}  |  IPO: {ipo_date}

Company Description (FMP):
{description[:1500]}

Business Section from 10-K (SEC EDGAR):
{business_text}

Prior knowledge base context:
{context_str}

Assess the business quality and competitive positioning. Return JSON signal.
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
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "market_cap_b": mkt_cap_b,
            "summary": f"BroadAnalysis: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


async def _fetch_all(symbol: str) -> tuple[dict, str, dict]:
    """Fetch profile, business section, and info in parallel."""
    import asyncio
    profile_task = asyncio.create_task(fmp_svc.get_company_profile(symbol))
    business_task = asyncio.create_task(edgar_svc.get_business_section(symbol))
    info_task = asyncio.create_task(yf_svc.get_info(symbol))
    return await asyncio.gather(profile_task, business_task, info_task)
