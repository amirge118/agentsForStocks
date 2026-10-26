"""FinancialHistoryAgent — five-year statement trends and CAGRs (FMP)."""

import asyncio
from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AnalysisResult, neutral_fallback
from app.agents.formatting import billions, knowledge_block, pct, table
from app.agents.registry import register_agent
from app.domain.financials import growth_rates
from app.knowledge.store import Learning

_NOTABLE_REVENUE_CAGR = 0.15


class FinancialHistoryResult(AnalysisResult):
    revenue_cagr: float
    fcf_cagr: float
    net_income_cagr: float


@dataclass(frozen=True)
class FinancialHistoryData:
    income: list[dict]
    balance: list[dict]
    cash_flow: list[dict]
    ratios: list[dict]


@register_agent(
    "financial_history",
    description="Five-year revenue, profit, cash-flow and balance-sheet trends (FMP)",
    recommendation_weight=20,
)
class FinancialHistoryAgent(Agent[FinancialHistoryData, FinancialHistoryResult]):
    result_model = FinancialHistoryResult

    async def fetch(self, symbol: str, run_date: date) -> FinancialHistoryData:
        income, balance, cash_flow, ratios = await asyncio.gather(
            self.ctx.fmp.get_income_statements(symbol, limit=5),
            self.ctx.fmp.get_balance_sheets(symbol, limit=5),
            self.ctx.fmp.get_cash_flow_statements(symbol, limit=5),
            self.ctx.fmp.get_financial_ratios(symbol, limit=5),
        )
        return FinancialHistoryData(income, balance, cash_flow, ratios)

    async def analyze(
        self, symbol: str, data: FinancialHistoryData, memory: list[str]
    ) -> FinancialHistoryResult:
        rates = growth_rates(data.income, data.cash_flow)
        if not data.income:
            reason = "No financial history data available"
            return FinancialHistoryResult(
                signal="neutral",
                confidence=0.0,
                reasoning=reason,
                revenue_cagr=0.0,
                fcf_cagr=0.0,
                net_income_cagr=0.0,
                summary=f"Financial history: neutral (0%) — {reason}",
            )

        judgement = await self.judge(
            _prompt(symbol, data, rates, memory), fallback=neutral_fallback()
        )
        return FinancialHistoryResult.from_judgement(
            "Financial history",
            judgement,
            detail=f"RevCAGR={rates.revenue_cagr:+.1%}",
            revenue_cagr=rates.revenue_cagr,
            fcf_cagr=rates.fcf_cagr,
            net_income_cagr=rates.net_income_cagr,
        )

    def learnings(self, symbol: str, result: FinancialHistoryResult) -> list[Learning]:
        learnings = super().learnings(symbol, result)
        if abs(result.revenue_cagr) > _NOTABLE_REVENUE_CAGR:
            trend = "growing" if result.revenue_cagr > 0 else "declining"
            learnings.append(
                Learning(
                    kind="pattern",
                    content=f"Revenue {trend} at {result.revenue_cagr:+.1%} CAGR over 5 years",
                    tags=("financials", "revenue", "trend"),
                )
            )
        return learnings


def _prompt(symbol: str, d: FinancialHistoryData, rates, memory: list[str]) -> str:
    income = table(
        "Year | Revenue | Gross profit | Net income | EBITDA",
        d.income,
        [
            ("revenue", billions),
            ("grossProfit", billions),
            ("netIncome", billions),
            ("ebitda", billions),
        ],
    )
    balance = table(
        "Year | Total debt | Cash | Equity",
        d.balance,
        [
            ("totalDebt", billions),
            ("cashAndCashEquivalents", billions),
            ("totalStockholdersEquity", billions),
        ],
    )
    cash_flow = table(
        "Year | Operating CF | CapEx | Free CF",
        d.cash_flow,
        [
            ("operatingCashFlow", billions),
            ("capitalExpenditure", billions),
            ("freeCashFlow", billions),
        ],
    )
    ratios = table(
        "Year | Gross margin | Net margin | Op margin | ROE",
        d.ratios,
        [
            ("grossProfitMargin", pct),
            ("netProfitMargin", pct),
            ("operatingProfitMargin", pct),
            ("returnOnEquity", pct),
        ],
    )
    return f"""Symbol: {symbol}

Income statement (most recent first):
{income}

Balance sheet:
{balance}

Cash flow:
{cash_flow}

Margins and returns:
{ratios}

Five-year CAGRs (0% when not computable):
  Revenue: {rates.revenue_cagr:+.1%} | FCF: {rates.fcf_cagr:+.1%}
  Net income: {rates.net_income_cagr:+.1%}

{knowledge_block(memory)}"""
