"""
FundamentalsAgent — 4-factor fundamental analysis with majority voting.
Adapted from virattt/ai-hedge-fund fundamentals.py.

Factors:
  1. Profitability  — ROE, Net Margin, Operating Margin
  2. Growth         — Revenue, Earnings, Book Value growth
  3. Financial Health — Current Ratio, Debt/Equity, Free Cash Flow
  4. Valuation      — P/E, P/B, P/S (flags expensive, not a buy signal)

Signal = majority of the 4 sub-signals. Confidence from unanimity.
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal, SubSignal
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a fundamental stock analyst. You receive quantitative scores for four
dimensions and produce a final investment signal.
Return JSON with keys: signal ("bullish"|"bearish"|"neutral"), confidence (0-100), reasoning (string).
Keep reasoning under 200 characters. Base signal strictly on the scores provided.
"""


class FundamentalsAgent(AgentBase):
    agent_type = "fundamentals"

    async def fetch_data(self, symbol: str) -> dict:
        info = await yf_svc.get_info(symbol)
        history = await yf_svc.get_history(symbol, period="2y")

        return {
            "symbol": symbol,
            "info": info,
            "history": history,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        info = data["info"]
        symbol = data["symbol"]

        sub_signals: list[SubSignal] = [
            _score_profitability(info),
            _score_growth(info),
            _score_financial_health(info),
            _score_valuation(info),
        ]

        # Majority vote
        bullish = sum(1 for s in sub_signals if s.signal == "bullish")
        bearish = sum(1 for s in sub_signals if s.signal == "bearish")
        neutral = sum(1 for s in sub_signals if s.signal == "neutral")

        if bullish > bearish and bullish > neutral:
            majority = "bullish"
        elif bearish > bullish and bearish > neutral:
            majority = "bearish"
        else:
            majority = "neutral"

        # Confidence: how unanimous are the sub-signals?
        max_votes = max(bullish, bearish, neutral)
        confidence = (max_votes / len(sub_signals)) * 100.0

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}
Sub-signal scores:
  Profitability ({sub_signals[0].signal}, score={sub_signals[0].score:.1f}): {sub_signals[0].detail}
  Growth        ({sub_signals[1].signal}, score={sub_signals[1].score:.1f}): {sub_signals[1].detail}
  Fin. Health   ({sub_signals[2].signal}, score={sub_signals[2].score:.1f}): {sub_signals[2].detail}
  Valuation     ({sub_signals[3].signal}, score={sub_signals[3].score:.1f}): {sub_signals[3].detail}

Majority vote: {majority} ({max_votes}/4 agree), base confidence: {confidence:.0f}%
Prior knowledge base context: {context_str}

Produce the final signal JSON.
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
            "sub_signals": [s.model_dump() for s in sub_signals],
            "summary": f"Fundamentals: {result.signal} ({result.confidence:.0f}%) — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }


# ---------------------------------------------------------------------------
# Sub-scoring functions (adapted from ai-hedge-fund)
# ---------------------------------------------------------------------------

def _score_profitability(info: dict) -> SubSignal:
    """ROE >15%, Net Margin >20%, Op Margin >15% — bullish if 2+ pass."""
    checks = [
        (info.get("returnOnEquity") or 0) > 0.15,
        (info.get("profitMargins") or 0) > 0.20,
        (info.get("operatingMargins") or 0) > 0.15,
    ]
    passed = sum(checks)
    roe = f"ROE={info.get('returnOnEquity', 0):.1%}"
    nm = f"NM={info.get('profitMargins', 0):.1%}"
    om = f"OM={info.get('operatingMargins', 0):.1%}"
    detail = f"{roe} {nm} {om}"

    if passed >= 2:
        return SubSignal(name="profitability", signal="bullish", score=passed * 3.33, detail=detail)
    if passed == 0:
        return SubSignal(name="profitability", signal="bearish", score=1.0, detail=detail)
    return SubSignal(name="profitability", signal="neutral", score=5.0, detail=detail)


def _score_growth(info: dict) -> SubSignal:
    """Revenue, Earnings, Book Value growth >10% — bullish if 2+ pass."""
    checks = [
        (info.get("revenueGrowth") or 0) > 0.10,
        (info.get("earningsGrowth") or 0) > 0.10,
        (info.get("bookValueGrowth") or info.get("bookValue") or 0) > 0,
    ]
    passed = sum(checks)
    rg = f"Rev={info.get('revenueGrowth', 0):.1%}"
    eg = f"Earn={info.get('earningsGrowth', 0):.1%}"
    detail = f"{rg} {eg}"

    if passed >= 2:
        return SubSignal(name="growth", signal="bullish", score=passed * 3.33, detail=detail)
    if passed == 0:
        return SubSignal(name="growth", signal="bearish", score=1.0, detail=detail)
    return SubSignal(name="growth", signal="neutral", score=5.0, detail=detail)


def _score_financial_health(info: dict) -> SubSignal:
    """Current Ratio >1.5, D/E <0.5, FCF positive — bullish if 2+ pass."""
    checks = [
        (info.get("currentRatio") or 0) > 1.5,
        (info.get("debtToEquity") or 999) < 50,    # yfinance returns % (e.g. 45 = 0.45)
        (info.get("freeCashflow") or 0) > 0,
    ]
    passed = sum(checks)
    cr = f"CR={info.get('currentRatio', 0):.1f}"
    de = f"D/E={info.get('debtToEquity', 0):.0f}%"
    fcf = f"FCF={'pos' if info.get('freeCashflow', 0) > 0 else 'neg'}"
    detail = f"{cr} {de} {fcf}"

    if passed >= 2:
        return SubSignal(name="financial_health", signal="bullish", score=passed * 3.33, detail=detail)
    if passed == 0:
        return SubSignal(name="financial_health", signal="bearish", score=1.0, detail=detail)
    return SubSignal(name="financial_health", signal="neutral", score=5.0, detail=detail)


def _score_valuation(info: dict) -> SubSignal:
    """P/E <25, P/B <3, P/S <5 — bearish if expensive (thresholds exceeded 2+)."""
    expensive = [
        0 < (info.get("trailingPE") or 0) > 25,
        0 < (info.get("priceToBook") or 0) > 3,
        0 < (info.get("priceToSalesTrailing12Months") or 0) > 5,
    ]
    n_expensive = sum(expensive)
    pe = f"P/E={info.get('trailingPE', 'N/A')}"
    pb = f"P/B={info.get('priceToBook', 'N/A')}"
    ps = f"P/S={info.get('priceToSalesTrailing12Months', 'N/A')}"
    detail = f"{pe} {pb} {ps}"

    if n_expensive >= 2:
        return SubSignal(name="valuation", signal="bearish", score=2.0, detail=detail)
    if n_expensive == 0:
        return SubSignal(name="valuation", signal="bullish", score=8.0, detail=detail)
    return SubSignal(name="valuation", signal="neutral", score=5.0, detail=detail)
