"""GrowthAgent — growth potential from earnings-call transcripts and analyst estimates (FMP)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent
from app.domain.financials import yearly_revenue_growth

_TRANSCRIPTS_IN_PROMPT = 2
_TRANSCRIPT_CHARS = 5_000


class GrowthResult(AnalysisResult):
    transcript_available: bool
    analyst_coverage: int


@dataclass(frozen=True)
class GrowthData:
    transcripts: list[dict]  # most recent first
    estimates: list[dict]
    income: list[dict]


@register_agent(
    "growth",
    description="Growth outlook from earnings calls and forward estimates (FMP)",
    recommendation_weight=10,
)
class GrowthAgent(Agent[GrowthData, GrowthResult]):
    result_model = GrowthResult

    async def fetch(self, symbol: str, run_date: date) -> GrowthData:
        fmp = self.ctx.fmp
        year = run_date.year
        q1, q2, estimates, income = await asyncio.gather(
            fmp.get_earnings_call_transcript(symbol, year, 1),
            fmp.get_earnings_call_transcript(symbol, year, 2),
            fmp.get_analyst_estimates(symbol, limit=5),
            fmp.get_income_statements(symbol, limit=3),
        )
        transcripts = [t for t in (q2, q1) if t]
        if not transcripts:  # early in the year: fall back to last year's H2 calls
            q3, q4 = await asyncio.gather(
                fmp.get_earnings_call_transcript(symbol, year - 1, 3),
                fmp.get_earnings_call_transcript(symbol, year - 1, 4),
            )
            transcripts = [t for t in (q4, q3) if t]
        return GrowthData(transcripts=transcripts, estimates=estimates, income=income)

    async def analyze(self, symbol: str, data: GrowthData, memory: list[str]) -> GrowthResult:
        judgement = await self.judge(
            f"""Symbol: {symbol}

Recent revenue growth (historical baseline):
{_format_growth(data.income)}

Analyst forward estimates:
{_format_estimates(data.estimates)}

Recent earnings call transcript(s):
{_format_transcripts(data.transcripts)}

{knowledge_block(memory)}""",
            fallback=neutral_fallback(),
        )
        return GrowthResult.from_judgement(
            "Growth",
            judgement,
            transcript_available=bool(data.transcripts),
            analyst_coverage=len(data.estimates),
        )


def _format_growth(income: list[dict]) -> str:
    rows = yearly_revenue_growth(income)
    return "\n".join(f"  {year}: {growth:+.1%}" for year, growth in rows) or "Insufficient data."


def _format_estimates(estimates: list[dict]) -> str:
    if not estimates:
        return "No analyst estimates available."
    lines = ["Year | Est. revenue | Est. EPS | # analysts"]
    for e in estimates[:4]:
        rev, eps = e.get("revenueAvg"), e.get("epsAvg")
        analysts = e.get("numAnalystsRevenue") or e.get("numAnalystsEps") or 0
        lines.append(
            f"{str(e.get('date') or '?')[:4]} | {f'${rev / 1e9:.2f}B' if rev else 'N/A'} | "
            f"{f'${eps:.2f}' if eps else 'N/A'} | {analysts}"
        )
    return "\n".join(lines)


def _format_transcripts(transcripts: list[dict]) -> str:
    parts = []
    for t in transcripts[:_TRANSCRIPTS_IN_PROMPT]:
        content = (t.get("content") or "")[:_TRANSCRIPT_CHARS]
        if content:
            label = (
                f"Q{t.get('quarter', '?')} {t.get('year', '?')} ({str(t.get('date') or '')[:10]})"
            )
            parts.append(f"--- {label} ---\n{content}")
    return "\n\n".join(parts) or "No earnings call transcripts available."
