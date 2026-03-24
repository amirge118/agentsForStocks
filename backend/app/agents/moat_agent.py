"""
MoatAgent — competitive advantage and economic moat assessment.
Level 3 of the 10-level stock analysis framework.

Data sources:
  - SEC EDGAR 10-K Item 1 (Business section — patents, switching costs, network effects)
  - FMP financial ratios (margin durability over 5 years)
  - FMP balance sheets (intangible assets as % of total assets)
  - FMP company profile (industry context)
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import edgar_service as edgar_svc
from app.services import fmp_service as fmp_svc
from app.services import llm_service

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a competitive analysis expert identifying economic moats.
Assess: brand strength, network effects, switching costs, cost advantages, patents/IP,
regulatory licenses, and margin durability (stable high margins = pricing power).
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — name the specific moat type or lack thereof).
Bullish = clear durable moat. Bearish = no moat, commodity business, eroding margins.
"""

# Keywords that indicate moat-type advantages in 10-K text
_MOAT_KEYWORDS = [
    "patent", "trademark", "proprietary", "switching cost", "network effect",
    "economies of scale", "brand", "license", "regulatory", "exclusive",
    "barrier to entry", "platform", "installed base", "recurring revenue",
]


class MoatAgent(AgentBase):
    agent_type = "moat"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        business_text, ratios, balance, profile = await asyncio.gather(
            edgar_svc.get_business_section(symbol),
            fmp_svc.get_financial_ratios(symbol, limit=5),
            fmp_svc.get_balance_sheets(symbol, limit=3),
            fmp_svc.get_company_profile(symbol),
        )
        return {
            "symbol": symbol,
            "business_text": business_text,
            "ratios": ratios,
            "balance": balance,
            "profile": profile,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        business_text = data["business_text"]
        ratios = data["ratios"]
        balance = data["balance"]
        profile = data["profile"]

        # Count moat keyword hits in 10-K
        keyword_hits = _count_keywords(business_text)
        keyword_list = ", ".join(keyword_hits) if keyword_hits else "none detected"

        # Gross margin durability: variance across years
        gp_margins = [r.get("grossProfitMargin") for r in ratios if r.get("grossProfitMargin") is not None]
        avg_gp_margin = sum(gp_margins) / len(gp_margins) if gp_margins else 0.0
        gp_variance = _variance(gp_margins)

        # Intangibles as % of total assets (proxy for brand/IP value)
        intangibles_pct = 0.0
        if balance:
            b = balance[0]
            intangibles = b.get("goodwillAndIntangibleAssets") or 0
            total_assets = b.get("totalAssets") or 1
            intangibles_pct = intangibles / total_assets if total_assets > 0 else 0.0

        industry = profile.get("industry") or "Unknown"

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}  |  Industry: {industry}

Moat keyword hits in 10-K: {keyword_list}

Gross Profit Margin (5yr avg): {avg_gp_margin * 100:.1f}%
Gross Margin Stability (lower variance = more pricing power): {gp_variance * 100:.2f}%
Intangibles / Total Assets: {intangibles_pct * 100:.1f}%

10-K Business Section (relevant excerpt):
{business_text[:6000]}

Prior knowledge base context:
{context_str}

Identify the type and strength of competitive moat. Return JSON signal.
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
            "avg_gross_margin": avg_gp_margin,
            "gp_margin_variance": gp_variance,
            "intangibles_pct": intangibles_pct,
            "moat_keywords": keyword_hits,
            "summary": f"Moat: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        keywords = result.get("moat_keywords", [])
        if keywords and result.get("signal") == "bullish":
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Moat indicators detected: {', '.join(keywords[:5])}",
                    tags=["moat", "competitive_advantage"],
                )
            )
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


def _count_keywords(text: str) -> list[str]:
    """Return list of moat keywords found in the text (case-insensitive, deduplicated)."""
    text_lower = text.lower()
    return [kw for kw in _MOAT_KEYWORDS if kw in text_lower]


def _variance(values: list[float]) -> float:
    """Sample variance of a list of floats. Returns 0 if < 2 values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)
