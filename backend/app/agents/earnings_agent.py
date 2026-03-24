"""
EarningsAgent — earnings report quality, surprise history, and post-earnings reaction.
Level 8 of the 10-level stock analysis framework.

Data sources:
  - FMP earnings surprises (last 8 quarters: actual vs estimated EPS)
  - yfinance get_earnings_dates (next earnings date)
  - yfinance get_history (2yr daily — to compute post-earnings stock reaction)
  - FMP income statements (EPS trend)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import fmp_service as fmp_svc
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an earnings quality analyst. Assess a company's track record of beating
earnings estimates and how the market reacts to earnings reports.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — focus on beat rate, surprise magnitude, and stock reaction).
Bullish = consistent beats, positive market reaction, improving guidance.
Bearish = frequent misses, negative market reaction, guidance cuts.
"""


class EarningsAgent(AgentBase):
    agent_type = "earnings"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        surprises, earnings_dates, history = await asyncio.gather(
            fmp_svc.get_earnings_surprises(symbol),
            yf_svc.get_earnings_dates(symbol),
            yf_svc.get_history(symbol, period="2y", interval="1d"),
        )
        return {
            "symbol": symbol,
            "surprises": surprises,
            "earnings_dates": earnings_dates,
            "history": history,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        surprises = data["surprises"]
        earnings_dates_df = data["earnings_dates"]
        history = data["history"]

        # Compute surprise statistics
        surprise_stats = _compute_surprise_stats(surprises)

        # Compute post-earnings price reactions
        reactions = _compute_post_earnings_reactions(surprises, history)

        # Next earnings date
        next_earnings = _get_next_earnings(earnings_dates_df)

        # Format for prompt
        surprises_str = _format_surprises(surprises, reactions)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

Earnings Surprise History (last 8 quarters, most recent first):
{surprises_str}

Summary Statistics:
  Beat rate:              {surprise_stats['beat_rate'] * 100:.0f}%  ({surprise_stats['beats']}/{surprise_stats['total']} quarters)
  Average surprise:       {surprise_stats['avg_surprise']:+.1f}%
  Avg 1-day post-earnings return: {reactions.get('avg_1d_return', 0):+.1f}%
  Avg 3-day post-earnings return: {reactions.get('avg_3d_return', 0):+.1f}%

Next earnings date: {next_earnings}

Prior knowledge base context:
{context_str}

Assess earnings quality and execution consistency. Return JSON signal.
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
            "beat_rate": surprise_stats["beat_rate"],
            "avg_surprise_pct": surprise_stats["avg_surprise"],
            "avg_1d_return": reactions.get("avg_1d_return", 0.0),
            "next_earnings": next_earnings,
            "summary": f"Earnings: {result.signal} ({result.confidence:.0f}%) beat_rate={surprise_stats['beat_rate']:.0%} — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        beat_rate = result.get("beat_rate", 0)
        if beat_rate >= 0.75:
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Consistent earnings beater: {beat_rate:.0%} beat rate",
                    tags=["earnings", "execution", "beat"],
                )
            )
        elif beat_rate <= 0.40:
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Frequent earnings misser: {beat_rate:.0%} beat rate",
                    tags=["earnings", "execution", "miss"],
                )
            )
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


def _compute_surprise_stats(surprises: list[dict]) -> dict:
    if not surprises:
        return {"beat_rate": 0.0, "beats": 0, "total": 0, "avg_surprise": 0.0}
    beats = 0
    surprise_pcts = []
    for s in surprises[:8]:
        actual = s.get("actualEarningResult")
        estimated = s.get("estimatedEarning")
        if actual is None or estimated is None:
            continue
        if abs(estimated) > 0:
            pct = (actual - estimated) / abs(estimated) * 100
            surprise_pcts.append(pct)
            if actual > estimated:
                beats += 1
    total = len(surprise_pcts)
    return {
        "beat_rate": beats / total if total > 0 else 0.0,
        "beats": beats,
        "total": total,
        "avg_surprise": sum(surprise_pcts) / total if total > 0 else 0.0,
    }


def _compute_post_earnings_reactions(
    surprises: list[dict], history: pd.DataFrame
) -> dict:
    """Compute average 1-day and 3-day returns following each earnings date."""
    if history.empty or not surprises:
        return {"avg_1d_return": 0.0, "avg_3d_return": 0.0}

    history = history.copy()
    history.index = pd.to_datetime(history.index).tz_localize(None)
    close = history["Close"]

    returns_1d = []
    returns_3d = []

    for s in surprises[:8]:
        date_str = s.get("date")
        if not date_str:
            continue
        try:
            earn_date = pd.Timestamp(date_str[:10])
        except Exception:
            continue

        # Find the first trading day on or after the earnings date
        future_dates = close.index[close.index >= earn_date]
        if len(future_dates) < 4:
            continue
        d0 = future_dates[0]
        d1 = future_dates[1]
        d3 = future_dates[3]

        p0 = close.get(d0)
        p1 = close.get(d1)
        p3 = close.get(d3)

        if p0 and p0 > 0:
            if p1:
                returns_1d.append((p1 - p0) / p0 * 100)
            if p3:
                returns_3d.append((p3 - p0) / p0 * 100)

    return {
        "avg_1d_return": sum(returns_1d) / len(returns_1d) if returns_1d else 0.0,
        "avg_3d_return": sum(returns_3d) / len(returns_3d) if returns_3d else 0.0,
    }


def _get_next_earnings(earnings_dates_df: pd.DataFrame) -> str:
    if earnings_dates_df is None or earnings_dates_df.empty:
        return "Unknown"
    try:
        future = earnings_dates_df[
            earnings_dates_df.index > pd.Timestamp.now(tz="UTC")
        ]
        if future.empty:
            return "Unknown"
        return str(future.index[0].date())
    except Exception:
        return "Unknown"


def _format_surprises(surprises: list[dict], reactions: dict) -> str:
    if not surprises:
        return "No earnings surprise data available."
    lines = ["Date       | Actual EPS | Est. EPS | Surprise%"]
    for s in surprises[:8]:
        actual = s.get("actualEarningResult")
        est = s.get("estimatedEarning")
        date = (s.get("date") or "?")[:10]
        if actual is not None and est is not None and abs(est) > 0:
            surp = (actual - est) / abs(est) * 100
            lines.append(f"{date} | ${actual:>8.3f} | ${est:>8.3f} | {surp:>+7.1f}%")
        else:
            lines.append(f"{date} | {'N/A':>9} | {'N/A':>9} | N/A")
    return "\n".join(lines)
