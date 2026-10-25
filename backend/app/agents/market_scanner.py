"""MarketScannerAgent — quick end-of-day scan: price change, SMA position, volume, multiples."""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.agents.base import Agent, AnalysisResult
from app.agents.formatting import memory_block
from app.agents.registry import register_agent
from app.core.context import note_fallback
from app.domain.market_scan import ScanMetrics, scan_metrics
from app.domain.signals import SignalLabel
from app.knowledge.store import Learning
from app.llm.client import LLMError
from app.llm.prompt_loader import load_prompt


class ScanJudgement(BaseModel):
    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str
    observations: list[str]
    risk_level: Literal["low", "medium", "high"]


class MarketScanResult(AnalysisResult):
    observations: list[str]
    risk_level: Literal["low", "medium", "high"]
    metrics: dict[str, float | None]


@dataclass(frozen=True)
class MarketScanData:
    info: dict
    history: pd.DataFrame


@register_agent("market_scanner", description="End-of-day price, trend and volume scan")
class MarketScannerAgent(Agent[MarketScanData, MarketScanResult]):
    result_model = MarketScanResult

    async def fetch(self, symbol: str, run_date: date) -> MarketScanData:
        info, history = await asyncio.gather(
            self.ctx.yfinance.get_info(symbol),
            self.ctx.yfinance.get_history(symbol, period="3mo"),
        )
        return MarketScanData(info=info, history=history)

    async def analyze(
        self, symbol: str, data: MarketScanData, memory: list[str]
    ) -> MarketScanResult:
        m = scan_metrics(data.info, data.history)
        try:
            judgement = await self.ctx.llm.generate(
                system=load_prompt(self.name),
                prompt=self.with_data_gaps(_prompt(symbol, data.info, m, memory)),
                schema=ScanJudgement,
                max_tokens=512,
                prompt_name=self.name,
            )
        except LLMError:
            note_fallback()
            judgement = ScanJudgement(
                signal="neutral",
                confidence=0.0,
                reasoning="LLM unavailable — scan metrics stored without judgement",
                observations=["volume spike"] if m.volume_spike else [],
                risk_level="medium",
            )
        return MarketScanResult(
            signal=judgement.signal,
            confidence=judgement.confidence,
            reasoning=judgement.reasoning,
            observations=judgement.observations,
            risk_level=judgement.risk_level,
            metrics={
                "price": m.price,
                "change_pct": m.change_pct,
                "sma_20": m.sma_20,
                "sma_50": m.sma_50,
                "price_vs_sma20_pct": m.price_vs_sma20_pct,
                "volume_ratio": m.volume_ratio,
            },
            summary=f"Market scan: {judgement.signal} ({judgement.confidence:.0f}%) "
            f"risk={judgement.risk_level} — {judgement.reasoning}",
        )

    def learnings(self, symbol: str, result: MarketScanResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        ratio = result.metrics.get("volume_ratio")
        if ratio is not None and ratio > 2.0:
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Volume spike {ratio:.1f}x average. Signals: {result.observations}",
                    tags=("volume", "anomaly"),
                )
            )
        return learnings


def _prompt(symbol: str, info: dict, m: ScanMetrics, memory: list[str]) -> str:
    change = f"{m.change_pct:+.2f}%" if m.change_pct is not None else "N/A"
    return f"""Symbol: {symbol}
Price: {m.price} ({change} today)
Sector: {info.get('sector') or 'N/A'}
Market cap: {info.get('marketCap') or 'N/A'}
Trailing P/E: {info.get('trailingPE') or 'N/A'} | Forward P/E: {info.get('forwardPE') or 'N/A'}
SMA20: {m.sma_20} | Price vs SMA20: {m.price_vs_sma20_pct}% | SMA50: {m.sma_50}
Volume vs average: {m.volume_ratio}x

Knowledge base context:
{memory_block(memory)}"""
