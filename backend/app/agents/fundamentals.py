"""FundamentalsAgent — profitability, growth, financial health and valuation majority vote."""

from datetime import date

from pydantic import BaseModel

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent
from app.domain.fundamentals import FundamentalsVote, vote


class FactorView(BaseModel):
    name: str
    signal: str
    score: float
    detail: str


class FundamentalsResult(AnalysisResult):
    factors: list[FactorView]


@register_agent("fundamentals", description="Four-factor fundamental scoring (yfinance)")
class FundamentalsAgent(Agent[dict, FundamentalsResult]):
    result_model = FundamentalsResult

    async def fetch(self, symbol: str, run_date: date) -> dict:
        return await self.ctx.yfinance.get_info(symbol)

    async def analyze(self, symbol: str, data: dict, memory: list[str]) -> FundamentalsResult:
        result = vote(data)
        judgement = await self.judge(
            _prompt(symbol, result, memory),
            fallback=quant_fallback(
                result.majority, result.confidence, "four-factor majority vote"
            ),
        )
        return FundamentalsResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            factors=[
                FactorView(name=f.name, signal=f.signal, score=f.score, detail=f.detail)
                for f in result.factors
            ],
            summary=f"Fundamentals: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"— {judgement.reasoning}",
        )


def _prompt(symbol: str, result: FundamentalsVote, memory: list[str]) -> str:
    lines = "\n".join(
        f"  {f.name:<17} {f.signal:<8} score={f.score:.1f}  {f.detail}" for f in result.factors
    )
    return f"""Symbol: {symbol}
Factor scores:
{lines}

Majority vote: {result.majority} ({result.agreeing}/4 agree)
Base confidence: {result.confidence:.0f}%

Knowledge base context:
{memory_block(memory)}"""
