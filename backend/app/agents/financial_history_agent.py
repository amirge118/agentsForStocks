"""
FinancialHistoryAgent — 5-year financial trend analysis.
Level 2 of the 10-level stock analysis framework.

Data sources:
  - FMP income statements (5yr): revenue, profit, EBITDA
  - FMP balance sheets (5yr): debt, equity, cash
  - FMP cash flow statements (5yr): FCF, capex
  - FMP financial ratios (5yr): margins, ROE

Signal: bullish if revenue + FCF growing consistently with improving margins.
"""
from __future__ import annotations

import logging

from app.agents.base import AgentBase
from app.schemas.signals import AnalystSignal
from app.services import fmp_service as fmp_svc
from app.services import llm_service

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a financial analyst reviewing 5-year historical financial trends.
Assess revenue growth, profitability trends, FCF quality, and balance sheet strength.
Return ONLY valid JSON: signal ("bullish"|"bearish"|"neutral"), confidence (0-100),
reasoning (max 200 chars — focus on the dominant trend driving your signal).
"""


class FinancialHistoryAgent(AgentBase):
    agent_type = "financial_history"

    async def fetch_data(self, symbol: str) -> dict:
        import asyncio
        income, balance, cashflow, ratios = await asyncio.gather(
            fmp_svc.get_income_statements(symbol, limit=5),
            fmp_svc.get_balance_sheets(symbol, limit=5),
            fmp_svc.get_cash_flow_statements(symbol, limit=5),
            fmp_svc.get_financial_ratios(symbol, limit=5),
        )
        return {
            "symbol": symbol,
            "income": income,
            "balance": balance,
            "cashflow": cashflow,
            "ratios": ratios,
        }

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        symbol = data["symbol"]
        income = data["income"]
        balance = data["balance"]
        cashflow = data["cashflow"]
        ratios = data["ratios"]

        if not income:
            return _neutral(symbol, self.agent_type, "No financial history data available")

        # Build 5-year summary rows (most recent first)
        income_rows = _format_income(income)
        balance_rows = _format_balance(balance)
        cashflow_rows = _format_cashflow(cashflow)
        ratio_rows = _format_ratios(ratios)

        # Compute CAGRs from oldest to newest
        revenue_cagr = _cagr(income, "revenue")
        fcf_cagr = _cagr(cashflow, "freeCashFlow")
        net_income_cagr = _cagr(income, "netIncome")

        context_str = "\n".join(f"- {p}" for p in prior_context) if prior_context else "None"

        user_prompt = f"""
Symbol: {symbol}

5-Year Income Statement Trend (most recent first):
{income_rows}

5-Year Balance Sheet Trend:
{balance_rows}

5-Year Cash Flow Trend:
{cashflow_rows}

5-Year Margin & Return Ratios:
{ratio_rows}

Computed CAGRs (5-year):
  Revenue CAGR:    {revenue_cagr:+.1%} (N/A if insufficient data)
  FCF CAGR:        {fcf_cagr:+.1%}
  Net Income CAGR: {net_income_cagr:+.1%}

Prior knowledge base context:
{context_str}

Assess the quality and direction of this company's financial history. Return JSON signal.
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
            "revenue_cagr": revenue_cagr,
            "fcf_cagr": fcf_cagr,
            "net_income_cagr": net_income_cagr,
            "summary": f"FinancialHistory: {result.signal} ({result.confidence:.0f}%) RevCAGR={revenue_cagr:+.1%} — {result.reasoning}",
            "agent_type": self.agent_type,
            "symbol": symbol,
        }

    async def store_learnings(self, symbol: str, result: dict) -> None:
        rev_cagr = result.get("revenue_cagr", 0)
        if abs(rev_cagr) > 0.15:
            direction = "growing" if rev_cagr > 0 else "declining"
            await self._safe_write(
                self.knowledge.store_pattern(
                    symbol=symbol,
                    pattern=f"Revenue {direction} at {rev_cagr:+.1%} CAGR over 5 years",
                    tags=["financials", "revenue", "trend"],
                )
            )
        await self._safe_write(
            self.knowledge.store_analysis_result(
                symbol=symbol,
                summary=result.get("summary", ""),
                agent_type=self.agent_type,
            )
        )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_b(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"${val / 1e9:.2f}B"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def _format_income(rows: list[dict]) -> str:
    lines = ["Year       | Revenue    | Gross Profit | Net Income | EBITDA"]
    for r in rows:
        lines.append(
            f"{r.get('date','?')[:4]} | "
            f"{_fmt_b(r.get('revenue'))} | "
            f"{_fmt_b(r.get('grossProfit'))} | "
            f"{_fmt_b(r.get('netIncome'))} | "
            f"{_fmt_b(r.get('ebitda'))}"
        )
    return "\n".join(lines)


def _format_balance(rows: list[dict]) -> str:
    lines = ["Year       | Total Debt | Cash       | Equity"]
    for r in rows:
        lines.append(
            f"{r.get('date','?')[:4]} | "
            f"{_fmt_b(r.get('totalDebt'))} | "
            f"{_fmt_b(r.get('cashAndCashEquivalents'))} | "
            f"{_fmt_b(r.get('totalStockholdersEquity'))}"
        )
    return "\n".join(lines)


def _format_cashflow(rows: list[dict]) -> str:
    lines = ["Year       | Operating CF | CapEx       | Free CF"]
    for r in rows:
        lines.append(
            f"{r.get('date','?')[:4]} | "
            f"{_fmt_b(r.get('operatingCashFlow'))} | "
            f"{_fmt_b(r.get('capitalExpenditure'))} | "
            f"{_fmt_b(r.get('freeCashFlow'))}"
        )
    return "\n".join(lines)


def _format_ratios(rows: list[dict]) -> str:
    lines = ["Year       | Gross Margin | Net Margin | Op Margin | ROE"]
    for r in rows:
        lines.append(
            f"{r.get('date','?')[:4]} | "
            f"{_fmt_pct(r.get('grossProfitMargin'))} | "
            f"{_fmt_pct(r.get('netProfitMargin'))} | "
            f"{_fmt_pct(r.get('operatingProfitMargin'))} | "
            f"{_fmt_pct(r.get('returnOnEquity'))}"
        )
    return "\n".join(lines)


def _cagr(rows: list[dict], field: str) -> float:
    """Compute CAGR from oldest to newest year. Returns 0.0 if insufficient data."""
    if len(rows) < 2:
        return 0.0
    values = [r.get(field) for r in rows if r.get(field) is not None]
    if len(values) < 2:
        return 0.0
    oldest = values[-1]
    newest = values[0]
    n = len(values) - 1
    if oldest <= 0 or newest <= 0:
        return 0.0
    try:
        return (newest / oldest) ** (1 / n) - 1
    except (ZeroDivisionError, ValueError):
        return 0.0


def _neutral(symbol: str, agent_type: str, reason: str) -> dict:
    return {
        "signal": "neutral",
        "confidence": 0.0,
        "reasoning": reason,
        "revenue_cagr": 0.0,
        "fcf_cagr": 0.0,
        "net_income_cagr": 0.0,
        "summary": f"FinancialHistory: neutral (0%) — {reason}",
        "agent_type": agent_type,
        "symbol": symbol,
    }
