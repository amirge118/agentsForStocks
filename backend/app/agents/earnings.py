"""EarningsAgent — beat rate, surprise size and post-earnings price reaction (FMP + yfinance)."""

import asyncio
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import knowledge_block
from app.agents.registry import register_agent
from app.domain.earnings import (
    QUARTERS_ANALYZED,
    next_earnings_date,
    post_earnings_reaction,
    surprise_pct,
    surprise_stats,
)
from app.knowledge.store import Learning

_CONSISTENT_BEATER = 0.75
_FREQUENT_MISSER = 0.40


class EarningsResult(AnalysisResult):
    quarters_analyzed: int
    beat_rate: float
    avg_surprise_pct: float
    avg_1d_return: float
    next_earnings: str


@dataclass(frozen=True)
class EarningsData:
    surprises: list[dict]
    earnings_dates: pd.DataFrame
    history: pd.DataFrame


@register_agent(
    "earnings",
    description="Earnings surprise history and market reaction",
    recommendation_weight=5,
)
class EarningsAgent(Agent[EarningsData, EarningsResult]):
    result_model = EarningsResult

    async def fetch(self, symbol: str, run_date: date) -> EarningsData:
        surprises, earnings_dates, history = await asyncio.gather(
            self.ctx.fmp.get_earnings_surprises(symbol),
            self.ctx.yfinance.get_earnings_dates(symbol),
            self.ctx.yfinance.get_history(symbol, period="2y", interval="1d"),
        )
        return EarningsData(surprises, earnings_dates, history)

    async def analyze(self, symbol: str, data: EarningsData, memory: list[str]) -> EarningsResult:
        stats = surprise_stats(data.surprises)
        reaction = post_earnings_reaction(data.surprises, data.history)
        upcoming = next_earnings_date(data.earnings_dates)

        judgement = await self.judge(
            f"""Symbol: {symbol}

Earnings surprise history (last {QUARTERS_ANALYZED} quarters, most recent first):
{_format_surprises(data.surprises)}

Beat rate: {stats.beat_rate * 100:.0f}% ({stats.beats}/{stats.total} quarters)
Average surprise: {stats.avg_surprise_pct:+.1f}%
Average post-earnings return: 1 day {reaction.avg_1d_return_pct:+.1f}%, \
3 days {reaction.avg_3d_return_pct:+.1f}%
Next earnings date: {upcoming}

{knowledge_block(memory)}""",
            fallback=neutral_fallback(),
        )
        return EarningsResult.from_judgement(
            "Earnings",
            judgement,
            detail=f"beat_rate={stats.beat_rate:.0%}",
            quarters_analyzed=stats.total,
            beat_rate=stats.beat_rate,
            avg_surprise_pct=stats.avg_surprise_pct,
            avg_1d_return=reaction.avg_1d_return_pct,
            next_earnings=upcoming,
        )

    def learnings(self, symbol: str, result: EarningsResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        if not result.quarters_analyzed:
            return learnings  # no data is not a "misser"
        if result.beat_rate >= _CONSISTENT_BEATER:
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Consistent earnings beater: {result.beat_rate:.0%} beat rate",
                    tags=("earnings", "execution", "beat"),
                )
            )
        elif result.beat_rate <= _FREQUENT_MISSER:
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Frequent earnings misser: {result.beat_rate:.0%} beat rate",
                    tags=("earnings", "execution", "miss"),
                )
            )
        return learnings


def _format_surprises(surprises: list[dict]) -> str:
    if not surprises:
        return "No earnings surprise data available."
    lines = ["Date | Actual EPS | Est. EPS | Surprise"]
    for s in surprises[:QUARTERS_ANALYZED]:
        actual, est = s.get("actualEarningResult"), s.get("estimatedEarning")
        pct = surprise_pct(actual, est)
        day = str(s.get("date") or "?")[:10]
        if pct is None:
            lines.append(f"{day} | N/A | N/A | N/A")
        else:
            lines.append(f"{day} | ${actual:.3f} | ${est:.3f} | {pct:+.1f}%")
    return "\n".join(lines)
