"""TechnicalsAgent — trend, mean reversion, momentum, volatility and stat-arb composite."""

from datetime import date

import pandas as pd

from app.agents.base import Agent, AnalysisResult, quant_fallback
from app.agents.formatting import memory_block
from app.agents.registry import register_agent
from app.domain.technicals import STRATEGY_WEIGHTS, TechnicalSnapshot, analyze_price_history


class TechnicalsResult(AnalysisResult):
    strategies: dict[str, float]
    composite: float


# Twice the label threshold (±0.2): a composite this strong leaves no room for the
# opposite call. Five partly opposing strategies rarely push it past ±0.45.
_DECISIVE_COMPOSITE = 0.4


def _signal_agrees_with_a_decisive_composite(
    data: object, result: "TechnicalsResult"
) -> str | None:
    if result.composite >= _DECISIVE_COMPOSITE and result.signal == "bearish":
        return f"bearish against a strongly bullish composite ({result.composite:+.2f})"
    if result.composite <= -_DECISIVE_COMPOSITE and result.signal == "bullish":
        return f"bullish against a strongly bearish composite ({result.composite:+.2f})"
    return None


@register_agent(
    "technicals",
    description="Five-strategy technical analysis on 1y of prices",
    invariants=(_signal_agrees_with_a_decisive_composite,),
)
class TechnicalsAgent(Agent[pd.DataFrame, TechnicalsResult]):
    result_model = TechnicalsResult

    async def fetch(self, symbol: str, run_date: date) -> pd.DataFrame:
        return await self.ctx.yfinance.get_history(symbol, period="1y", interval="1d")

    async def analyze(self, symbol: str, data: pd.DataFrame, memory: list[str]) -> TechnicalsResult:
        snapshot = analyze_price_history(data)
        if snapshot is None:
            return TechnicalsResult(
                signal="neutral",
                confidence=0.0,
                reasoning="Insufficient price history for technical analysis.",
                strategies={},
                composite=0.0,
                summary="Technicals: neutral (0%) — insufficient data",
            )
        judgement = await self.judge(
            _prompt(symbol, snapshot, memory),
            fallback=quant_fallback(snapshot.label, snapshot.confidence, "weighted composite"),
        )
        return TechnicalsResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            strategies={k: float(v) for k, v in snapshot.strategies.items()},
            composite=float(snapshot.composite),
            summary=f"Technicals: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"— {judgement.reasoning}",
        )


def _prompt(symbol: str, snapshot: TechnicalSnapshot, memory: list[str]) -> str:
    lines = "\n".join(
        f"  {name} (weight={weight:.0%}): {snapshot.strategies[name]:+.3f}"
        for name, weight in STRATEGY_WEIGHTS
    )
    return f"""Symbol: {symbol}
Strategy signals (-1 = bearish, +1 = bullish):
{lines}
Composite weighted signal: {snapshot.composite:+.3f} → {snapshot.label}

Knowledge base context:
{memory_block(memory)}"""
