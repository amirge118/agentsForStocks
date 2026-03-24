"""
Signal aggregator — combines outputs from multiple analyst agents into
a single ConsolidatedSignal per symbol.

Usage:
    results = await run_all_agents(symbol, db, knowledge)
    consolidated = aggregate_signals(symbol, results)
"""
from __future__ import annotations

import logging

from app.schemas.signals import AnalystSignal, ConsolidatedSignal

logger = logging.getLogger(__name__)

_SIGNAL_WEIGHT: dict[str, float] = {
    "fundamentals":   1.0,
    "technicals":     1.0,
    "sentiment":      0.8,
    "valuation":      1.2,   # weighted higher — most objective method
    "market_scanner": 0.6,   # broad scan, lower weight in aggregation
}


def aggregate_signals(symbol: str, agent_results: list[dict]) -> ConsolidatedSignal:
    """
    Aggregate multiple agent result dicts into a ConsolidatedSignal.

    agent_results: list of dicts, each must have keys:
        signal, confidence, reasoning, agent_type, symbol
    """
    signals: list[AnalystSignal] = []
    for r in agent_results:
        try:
            signals.append(AnalystSignal(
                signal=r["signal"],
                confidence=float(r.get("confidence", 50.0)),
                reasoning=r.get("reasoning", ""),
                agent_type=r.get("agent_type", "unknown"),
                symbol=symbol,
            ))
        except Exception as exc:
            logger.warning("Skipping malformed agent result: %s", exc)

    if not signals:
        return ConsolidatedSignal(
            symbol=symbol,
            signal="neutral",
            confidence=0.0,
            bullish_count=0,
            bearish_count=0,
            neutral_count=0,
            agent_signals=[],
            reasoning="No valid agent signals received.",
        )

    # Weighted vote
    weighted_bullish = 0.0
    weighted_bearish = 0.0
    weighted_neutral = 0.0

    for s in signals:
        weight = _SIGNAL_WEIGHT.get(s.agent_type, 1.0)
        conf_weight = weight * (s.confidence / 100.0)
        if s.signal == "bullish":
            weighted_bullish += conf_weight
        elif s.signal == "bearish":
            weighted_bearish += conf_weight
        else:
            weighted_neutral += conf_weight

    total = weighted_bullish + weighted_bearish + weighted_neutral
    if total == 0:
        overall = "neutral"
        confidence = 0.0
    elif weighted_bullish > weighted_bearish and weighted_bullish > weighted_neutral:
        overall = "bullish"
        confidence = (weighted_bullish / total) * 100.0
    elif weighted_bearish > weighted_bullish and weighted_bearish > weighted_neutral:
        overall = "bearish"
        confidence = (weighted_bearish / total) * 100.0
    else:
        overall = "neutral"
        confidence = (weighted_neutral / total) * 100.0

    # Raw counts for transparency
    bullish_count = sum(1 for s in signals if s.signal == "bullish")
    bearish_count = sum(1 for s in signals if s.signal == "bearish")
    neutral_count = sum(1 for s in signals if s.signal == "neutral")

    # Build reasoning summary
    signal_lines = [
        f"{s.agent_type}: {s.signal} ({s.confidence:.0f}%)"
        for s in signals
    ]
    reasoning = f"{overall.upper()} consensus ({confidence:.0f}%) from {len(signals)} agents. " + " | ".join(signal_lines)

    return ConsolidatedSignal(
        symbol=symbol,
        signal=overall,
        confidence=round(confidence, 1),
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        neutral_count=neutral_count,
        agent_signals=signals,
        reasoning=reasoning,
    )


async def run_all_agents(
    symbol: str,
    db,
    knowledge,
    agents: list[str] | None = None,
) -> list[dict]:
    """
    Run all analyst agents for a symbol concurrently and return their results.
    agents: optional list of agent_type strings to restrict which run.
    """
    import asyncio
    from app.agents.fundamentals_agent import FundamentalsAgent
    from app.agents.technicals_agent import TechnicalsAgent
    from app.agents.sentiment_agent import SentimentAgent
    from app.agents.valuation_agent import ValuationAgent
    from app.agents.market_scanner import MarketScannerAgent

    all_agents = {
        "fundamentals": FundamentalsAgent,
        "technicals": TechnicalsAgent,
        "sentiment": SentimentAgent,
        "valuation": ValuationAgent,
        "market_scanner": MarketScannerAgent,
    }

    selected = {k: v for k, v in all_agents.items() if agents is None or k in agents}

    async def _run_one(agent_cls) -> dict | None:
        try:
            agent = agent_cls(db=db, knowledge=knowledge)
            data = await agent.fetch_data(symbol)
            prior = await knowledge.recall_for_symbol(symbol, agent.agent_type)
            result = await agent.analyze(data, prior_context=prior)
            await agent.store_learnings(symbol, result)
            return result
        except Exception as exc:
            logger.error("Agent %s failed for %s: %s", agent_cls.__name__, symbol, exc)
            return None

    tasks = [_run_one(cls) for cls in selected.values()]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]
