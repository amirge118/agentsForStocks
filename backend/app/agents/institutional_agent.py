"""
InstitutionalAgent — institutional investor perspective from 13F filings.
Level 7 of the 10-level stock analysis framework.

Data sources:
  - FMP institutional holders (current top holders + change direction)
  - FMP 13F institutional ownership (last 4 quarters — trend)
  - yfinance info (heldPercentInstitutions, floatShares)

Signal: bullish if institutions are net accumulating; bearish if distributing.
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import fmp_service as fmp_svc
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a buy-side analyst reviewing institutional investor activity.
Assess whether smart money (large institutions, funds) is accumulating or distributing.
Key signals: net change in shares held, number of new positions, 13F quarterly trend.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — focus on the net institutional direction).
"""


class InstitutionalAgent(AgentBase):
    agent_type = "institutional"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        holders, ownership_trend, info = await asyncio.gather(
            fmp_svc.get_institutional_holders(symbol),
            fmp_svc.get_13f_institutional_ownership(symbol, limit=4),
            yf_svc.get_info(symbol),
        )
        return {
            "symbol": symbol,
            "holders": holders,
            "ownership_trend": ownership_trend,
            "info": info,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        holders = data["holders"]
        ownership_trend = data["ownership_trend"]
        info = data["info"]

        inst_pct = info.get("heldPercentInstitutions") or 0.0
        net_change = _net_institutional_change(holders)
        top_holders_str = _format_top_holders(holders)
        trend_str = _format_ownership_trend(ownership_trend)
        concentration = _top5_concentration(holders)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

Institutional ownership: {inst_pct * 100:.1f}% of shares outstanding
Net change across top holders: {net_change:+,.0f} shares
Top-5 holder concentration: {concentration * 100:.1f}% of institutional ownership

Top Institutional Holders (most recent):
{top_holders_str}

Quarterly 13F Ownership Trend (last 4 quarters):
{trend_str}

Prior knowledge base context:
{context_str}

Is smart money accumulating or distributing? Return JSON signal.
"""
        result = await llm_service.call_claude(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AnalystSignal,
        )

        direction = "accumulating" if net_change > 0 else "distributing" if net_change < 0 else "flat"

        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "institutional_pct": inst_pct,
            "net_share_change": net_change,
            "direction": direction,
            "top5_concentration": concentration,
            "summary": f"Institutional: {result.signal} ({result.confidence:.0f}%) {direction} — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        direction = result.get("direction", "")
        if direction in ("accumulating", "distributing"):
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Institutions {direction} — net change {result.get('net_share_change', 0):+,.0f} shares",
                    tags=["institutional", "smart_money"],
                )
            )
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


def _net_institutional_change(holders: list[dict]) -> float:
    """Sum of share changes across top 20 holders."""
    return sum(h.get("change") or 0 for h in holders[:20])


def _top5_concentration(holders: list[dict]) -> float:
    """Top-5 holders as fraction of total held by all listed holders."""
    if not holders:
        return 0.0
    total = sum(h.get("shares") or 0 for h in holders)
    top5 = sum(h.get("shares") or 0 for h in holders[:5])
    return top5 / total if total > 0 else 0.0


def _format_top_holders(holders: list[dict]) -> str:
    if not holders:
        return "No holder data available."
    lines = ["Holder                        | Shares      | Change"]
    for h in holders[:10]:
        name = (h.get("holder") or "Unknown")[:30]
        shares = h.get("shares") or 0
        change = h.get("change") or 0
        lines.append(f"{name:<30} | {shares:>12,.0f} | {change:>+12,.0f}")
    return "\n".join(lines)


def _format_ownership_trend(trend: list[dict]) -> str:
    if not trend:
        return "No 13F trend data available."
    lines = ["Date       | Investor                      | Shares       | Change"]
    for t in trend[:8]:
        date = (t.get("date") or "?")[:10]
        investor = (t.get("investorName") or "Unknown")[:30]
        shares = t.get("sharesNumber") or 0
        change = t.get("changeInSharesNumber") or 0
        lines.append(f"{date} | {investor:<30} | {shares:>12,.0f} | {change:>+12,.0f}")
    return "\n".join(lines)
