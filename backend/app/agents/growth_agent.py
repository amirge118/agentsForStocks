"""
GrowthAgent — growth potential assessment from earnings transcripts and analyst estimates.
Level 6 of the 10-level stock analysis framework.

Data sources:
  - FMP earnings call transcript (most recent 2 quarters)
  - FMP analyst estimates (forward 3-5 years)
  - FMP income statements (last 3 years for organic growth baseline)
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import fmp_service as fmp_svc
from app.services import llm_service

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a growth equity analyst assessing a company's future growth potential.
Analyze management guidance from earnings transcripts and forward analyst estimates.
Look for: TAM expansion, new product launches, geographic expansion, AI/tech advantages,
          organic revenue growth drivers.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — highlight the key growth driver or headwind).
"""


class GrowthAgent(AgentBase):
    agent_type = "growth"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        now = datetime.now()
        year = now.year
        # Try current year Q1 and Q2 transcripts (most recent guidance)
        transcript_q1, transcript_q2, estimates, income = await asyncio.gather(
            fmp_svc.get_earnings_call_transcript(symbol, year, 1),
            fmp_svc.get_earnings_call_transcript(symbol, year, 2),
            fmp_svc.get_analyst_estimates(symbol, limit=5),
            fmp_svc.get_income_statements(symbol, limit=3),
        )
        # Fall back to prior year Q3/Q4 if current year unavailable
        prior_q3 = {}
        prior_q4 = {}
        if not transcript_q1 and not transcript_q2:
            prior_q3, prior_q4 = await asyncio.gather(
                fmp_svc.get_earnings_call_transcript(symbol, year - 1, 3),
                fmp_svc.get_earnings_call_transcript(symbol, year - 1, 4),
            )
        return {
            "symbol": symbol,
            "transcripts": [t for t in [transcript_q2, transcript_q1, prior_q4, prior_q3] if t],
            "estimates": estimates,
            "income": income,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        transcripts = data["transcripts"]
        estimates = data["estimates"]
        income = data["income"]

        # Combine up to 2 transcript excerpts
        transcript_text = _combine_transcripts(transcripts)
        estimates_str = _format_estimates(estimates)
        growth_baseline = _revenue_growth_baseline(income)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

Recent Revenue Growth (historical baseline):
{growth_baseline}

Analyst Forward Estimates:
{estimates_str}

Recent Earnings Call Transcript(s):
{transcript_text}

Prior knowledge base context:
{context_str}

Assess growth potential. Look for: TAM, guidance language, new products, expansion plans.
Return JSON signal.
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
            "transcript_available": len(transcripts) > 0,
            "analyst_coverage": len(estimates),
            "summary": f"Growth: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
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


def _combine_transcripts(transcripts: list[dict]) -> str:
    if not transcripts:
        return "No earnings call transcripts available."
    parts = []
    for t in transcripts[:2]:
        label = f"Q{t.get('quarter', '?')} {t.get('year', '?')} ({t.get('date', '')[:10]})"
        content = t.get("content", "")[:5000]
        if content:
            parts.append(f"--- {label} ---\n{content}")
    return "\n\n".join(parts) if parts else "Transcripts empty."


def _format_estimates(estimates: list[dict]) -> str:
    if not estimates:
        return "No analyst estimates available."
    lines = ["Year | Est. Revenue | Est. EPS | # Analysts"]
    for e in estimates[:4]:
        rev = e.get("estimatedRevenueAvg")
        eps = e.get("estimatedEpsAvg")
        n = e.get("numberAnalystEstimatedRevenue") or e.get("numberAnalystsEstimatedEps") or 0
        rev_str = f"${rev / 1e9:.2f}B" if rev else "N/A"
        eps_str = f"${eps:.2f}" if eps else "N/A"
        lines.append(f"{e.get('date','?')[:4]} | {rev_str} | {eps_str} | {n}")
    return "\n".join(lines)


def _revenue_growth_baseline(income: list[dict]) -> str:
    if len(income) < 2:
        return "Insufficient historical data."
    lines = []
    for i in range(min(len(income) - 1, 3)):
        curr = income[i].get("revenue") or 0
        prev = income[i + 1].get("revenue") or 0
        if prev > 0:
            growth = (curr - prev) / prev
            lines.append(f"  {income[i].get('date','?')[:4]}: {growth:+.1%}")
    return "\n".join(lines) if lines else "N/A"
