"""
RecommendationAgent — final weighted scoring across all 8 analyst agents.
Level 9 of the 10-level stock analysis framework.

Data source: PostgreSQL agent_results table (today's results for all 8 agents).
This agent MUST run after all Phase 1 agents have completed for the same symbol + date.

Weighted scoring:
  financial_history: 20  valuation: 20  moat: 15  risk: 15
  broad_analysis: 10  growth: 10  institutional: 5  earnings: 5

Final output: BUY (score > +15), SELL (score < -15), HOLD (otherwise)
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from app.agents.base import AgentBase
from app.models.agent_result import AgentResult
from app.schemas.signals import AnalystSignal
from app.services import llm_service

logger = logging.getLogger(__name__)

_PHASE1_AGENTS = [
    "broad_analysis",
    "financial_history",
    "moat",
    "valuation",
    "risk",
    "growth",
    "institutional",
    "earnings",
]

_WEIGHTS = {
    "financial_history": 20,
    "valuation":         20,
    "moat":              15,
    "risk":              15,
    "broad_analysis":    10,
    "growth":            10,
    "institutional":      5,
    "earnings":           5,
}

# Buy if score > +15, Sell if score < -15, else Hold
_BUY_THRESHOLD = 15.0
_SELL_THRESHOLD = -15.0

_SYSTEM_PROMPT = """\
You are a portfolio manager making a final investment recommendation.
You receive weighted scores from 8 independent analysts.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — cite the 2-3 most important signals).
Bullish = strong buy thesis. Bearish = avoid / sell. Neutral = hold, insufficient conviction.
"""


class RecommendationAgent(AgentBase):
    agent_type = "recommendation"

    async def fetch_data(self, symbol: str) -> dict:
        """Query today's results from all Phase 1 agents."""
        today = date.today()
        agent_results: dict[str, dict] = {}

        for agent_type in _PHASE1_AGENTS:
            stmt = select(AgentResult).where(
                AgentResult.agent_type == agent_type,
                AgentResult.symbol == symbol,
                AgentResult.run_date == today,
            )
            row = await self.db.execute(stmt)
            result = row.scalar_one_or_none()
            if result and result.result_json:
                agent_results[agent_type] = result.result_json

        return {"symbol": symbol, "agent_results": agent_results}

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        agent_results = data["agent_results"]

        if len(agent_results) < 4:
            logger.warning(
                "RecommendationAgent: only %d/%d agents available for %s — insufficient for recommendation",
                len(agent_results), len(_PHASE1_AGENTS), symbol,
            )

        # Compute weighted score
        score, breakdown = _compute_weighted_score(agent_results)

        # Determine base recommendation
        if score > _BUY_THRESHOLD:
            base_action = "bullish"
        elif score < _SELL_THRESHOLD:
            base_action = "bearish"
        else:
            base_action = "neutral"

        base_conf = min(abs(score) * 3, 90.0)

        # Risk override: if risk agent is bearish with high confidence → cap at neutral
        risk_result = agent_results.get("risk", {})
        if risk_result.get("signal") == "bearish" and (risk_result.get("confidence") or 0) >= 70:
            if base_action == "bullish":
                base_action = "neutral"
                base_conf = min(base_conf, 55.0)
                logger.info("RecommendationAgent: risk override applied for %s", symbol)

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

Weighted Score: {score:+.1f} (Buy > +{_BUY_THRESHOLD}, Sell < {_SELL_THRESHOLD})
Base recommendation: {base_action} ({base_conf:.0f}%)

Agent breakdown (signal | confidence | weight | weighted contribution):
{_format_breakdown(breakdown)}

Missing agents: {[a for a in _PHASE1_AGENTS if a not in agent_results] or 'none'}

Prior knowledge base context:
{context_str}

Synthesize the agent signals into a final investment recommendation. Return JSON signal.
"""
        result = await llm_service.call_claude(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=AnalystSignal,
            model="claude-sonnet-4-6",  # Use stronger model for final recommendation
        )

        action = "BUY" if result.signal == "bullish" else "SELL" if result.signal == "bearish" else "HOLD"

        return {
            "signal": result.signal,
            "action": action,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "weighted_score": score,
            "agent_breakdown": breakdown,
            "agents_available": len(agent_results),
            "agents_missing": [a for a in _PHASE1_AGENTS if a not in agent_results],
            "summary": f"RECOMMENDATION: {action} ({result.confidence:.0f}%) score={score:+.1f} — {result.reasoning}",
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


def _compute_weighted_score(agent_results: dict[str, dict]) -> tuple[float, list[dict]]:
    """
    Convert each agent signal to +1/0/-1, weight by confidence and agent weight.
    Returns (total_score, breakdown_list).
    """
    signal_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
    breakdown = []
    total_score = 0.0

    for agent_type, weight in _WEIGHTS.items():
        result = agent_results.get(agent_type)
        if not result:
            breakdown.append({
                "agent": agent_type, "signal": "missing",
                "confidence": 0, "weight": weight, "contribution": 0.0,
            })
            continue

        signal = result.get("signal", "neutral")
        confidence = float(result.get("confidence") or 0)
        direction = signal_map.get(signal, 0.0)
        contribution = direction * (confidence / 100) * weight
        total_score += contribution

        breakdown.append({
            "agent": agent_type,
            "signal": signal,
            "confidence": confidence,
            "weight": weight,
            "contribution": contribution,
            "reasoning": result.get("reasoning", ""),
        })

    return total_score, breakdown


def _format_breakdown(breakdown: list[dict]) -> str:
    lines = [f"{'Agent':<20} | {'Signal':<8} | {'Conf':>4} | {'Wt':>3} | {'Contrib':>8}"]
    for b in breakdown:
        lines.append(
            f"{b['agent']:<20} | {b['signal']:<8} | {b['confidence']:>3.0f}% | "
            f"{b['weight']:>3} | {b['contribution']:>+8.2f}"
        )
    return "\n".join(lines)
