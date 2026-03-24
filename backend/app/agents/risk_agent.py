"""
RiskAgent — macro, regulatory, financial, and operational risk assessment.
Level 5 of the 10-level stock analysis framework.

Data sources:
  - SEC EDGAR 10-K Item 1A (Risk Factors — up to 20,000 chars)
  - FMP balance sheets (leverage, liquidity risk)
  - FMP key metrics (debt/equity, current ratio)
  - yfinance info (beta, short ratio)
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import edgar_service as edgar_svc
from app.services import fmp_service as fmp_svc
from app.services import llm_service
from app.services import yfinance_service as yf_svc

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a risk analyst assessing downside risks for an equity position.
Review the SEC Risk Factors section and financial leverage metrics.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — name the most significant risk category).
Bearish = high leverage + regulatory/competitive/macro risk clearly elevated.
Bullish = limited identifiable risks, strong balance sheet, low beta.
Neutral = moderate risk profile, standard for the sector.
"""

# High-risk keywords to detect in Risk Factors section
_HIGH_RISK_KEYWORDS = [
    "going concern", "material weakness", "restatement", "investigation",
    "litigation", "regulatory action", "covenant violation", "liquidity risk",
    "concentrated customer", "single customer", "customer concentration",
    "cybersecurity breach", "climate risk", "geopolitical",
]


class RiskAgent(AgentBase):
    agent_type = "risk"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        risk_text, balance, key_metrics, info = await asyncio.gather(
            edgar_svc.get_risk_factors(symbol),
            fmp_svc.get_balance_sheets(symbol, limit=3),
            fmp_svc.get_key_metrics(symbol, limit=1),
            yf_svc.get_info(symbol),
        )
        return {
            "symbol": symbol,
            "risk_text": risk_text,
            "balance": balance,
            "key_metrics": key_metrics,
            "info": info,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        risk_text = data["risk_text"]
        balance = data["balance"]
        key_metrics = data["key_metrics"]
        info = data["info"]

        # Financial risk metrics
        km = key_metrics[0] if key_metrics else {}
        debt_to_equity = km.get("debtToEquity") or info.get("debtToEquity") or 0.0
        current_ratio = km.get("currentRatio") or info.get("currentRatio") or 0.0
        beta = info.get("beta") or 1.0
        short_ratio = info.get("shortRatio") or 0.0

        # Cash vs debt trend from balance sheets
        liquidity_trend = _liquidity_trend(balance)

        # Count high-risk keyword hits
        risk_keywords_found = _find_risk_keywords(risk_text)
        risk_keyword_str = ", ".join(risk_keywords_found) if risk_keywords_found else "none"

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

Financial Risk Metrics:
  Debt/Equity ratio:     {debt_to_equity:.2f}
  Current ratio:         {current_ratio:.2f}  (>1.5 = healthy, <1.0 = stress)
  Beta (market risk):    {beta:.2f}
  Short ratio (days):    {short_ratio:.1f}
  Liquidity trend:       {liquidity_trend}

High-risk phrases found in Risk Factors: {risk_keyword_str}

10-K Risk Factors Section (Item 1A):
{risk_text[:8000]}

Prior knowledge base context:
{context_str}

Assess the overall risk profile. Return JSON signal (bearish = high risk, bullish = low risk).
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
            "debt_to_equity": debt_to_equity,
            "current_ratio": current_ratio,
            "beta": beta,
            "risk_keywords": risk_keywords_found,
            "summary": f"Risk: {result.signal} ({result.confidence:.0f}%) D/E={debt_to_equity:.1f} — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        keywords = result.get("risk_keywords", [])
        if keywords:
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Risk factors flagged: {', '.join(keywords[:5])}",
                    tags=["risk", "downside"],
                )
            )
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


def _find_risk_keywords(text: str) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in _HIGH_RISK_KEYWORDS if kw in text_lower]


def _liquidity_trend(balance: list[dict]) -> str:
    if not balance or len(balance) < 2:
        return "insufficient data"
    cash_latest = balance[0].get("cashAndCashEquivalents") or 0
    cash_prior = balance[-1].get("cashAndCashEquivalents") or 0
    debt_latest = balance[0].get("totalDebt") or 0
    debt_prior = balance[-1].get("totalDebt") or 0
    parts = []
    if cash_latest > cash_prior:
        parts.append("cash increasing")
    elif cash_latest < cash_prior:
        parts.append("cash declining")
    if debt_latest > debt_prior * 1.1:
        parts.append("debt rising")
    elif debt_latest < debt_prior * 0.9:
        parts.append("debt falling")
    return ", ".join(parts) if parts else "stable"
