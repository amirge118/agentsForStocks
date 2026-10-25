"""
Test doubles for the agent layer: fake providers with canned data and a fake
LLM. No network, no Anthropic API, no OpenViking.
"""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.agents.base import AgentContext
from app.llm.client import LLMError
from app.llm.profiles import ProfileBook


def price_history(days: int = 250, drift: float = 0.003, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + drift + rng.normal(0, 0.005, days))
    index = pd.bdate_range("2025-01-01", periods=days, tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": np.full(days, 1e6),
        },
        index=index,
    )


INFO = {
    "regularMarketPrice": 150.0,
    "previousClose": 148.0,
    "marketCap": 2.0e12,
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "trailingPE": 28.0,
    "forwardPE": 25.0,
    "volume": 3e6,
    "averageVolume": 1e6,
    "returnOnEquity": 0.9,
    "profitMargins": 0.25,
    "operatingMargins": 0.3,
    "revenueGrowth": 0.08,
    "earningsGrowth": 0.12,
    "bookValue": 4.0,
    "currentRatio": 1.1,
    "debtToEquity": 150.0,
    "freeCashflow": 1.0e11,
    "ebitda": 1.3e11,
    "netIncomeToCommon": 9.0e10,
    "totalDebt": 1.0e11,
    "totalCash": 6.0e10,
    "beta": 1.2,
    "shortRatio": 1.5,
    "heldPercentInstitutions": 0.6,
    "priceToBook": 40.0,
    "priceToSalesTrailing12Months": 7.0,
}


class FakeYFinance:
    def __init__(self, info: dict | None = None, history: pd.DataFrame | None = None) -> None:
        self.info = INFO if info is None else info
        self.history = price_history() if history is None else history

    async def get_info(self, symbol: str) -> dict:
        return self.info

    async def get_history(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> pd.DataFrame:
        return self.history

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        index = pd.DatetimeIndex(["2099-01-30", "2098-10-30"], tz="UTC")
        return pd.DataFrame({"EPS Estimate": [1.0, 1.0]}, index=index)

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        return [{"Transaction": "Purchase", "Start Date": date.today().isoformat()}] * 3

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        return [{"title": "Record iPhone sales"}, {"title": "New AI features"}]


class FakeFmp:
    def __init__(self, **overrides: Any) -> None:
        years = ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30", "2021-09-30"]
        self.data: dict[str, Any] = {
            "profile": {
                "companyName": "Apple",
                "industry": "Consumer Electronics",
                "sector": "Technology",
                "mktCap": 2.0e12,
                "description": "Phones.",
            },
            "income": [
                {
                    "date": y,
                    "revenue": 4e11 / 1.08**i,
                    "netIncome": 1e11 / 1.1**i,
                    "grossProfit": 1.8e11,
                    "ebitda": 1.3e11,
                }
                for i, y in enumerate(years)
            ],
            "balance": [
                {
                    "date": y,
                    "totalDebt": 1e11,
                    "cashAndCashEquivalents": 6e10 - i * 5e9,
                    "totalStockholdersEquity": 7e10,
                    "totalAssets": 3.5e11,
                    "goodwillAndIntangibleAssets": 0,
                }
                for i, y in enumerate(years)
            ],
            "cash_flow": [
                {
                    "date": y,
                    "freeCashFlow": 1e11 / 1.05**i,
                    "operatingCashFlow": 1.1e11,
                    "capitalExpenditure": -1e10,
                }
                for i, y in enumerate(years)
            ],
            "ratios": [
                {
                    "date": y,
                    "grossProfitMargin": 0.45,
                    "netProfitMargin": 0.25,
                    "operatingProfitMargin": 0.3,
                    "returnOnEquity": 1.5,
                }
                for y in years
            ],
            "key_metrics": [{"debtToEquity": 1.5, "currentRatio": 1.0}],
            "surprises": [
                {"date": "2025-10-30", "actualEarningResult": 1.6, "estimatedEarning": 1.5}
            ]
            * 4,
            "transcripts": {
                (2026, 2): {
                    "quarter": 2,
                    "year": 2026,
                    "date": "2026-07-30",
                    "content": "We expanded our services TAM.",
                }
            },
            "estimates": [
                {
                    "date": "2027-09-30",
                    "estimatedRevenueAvg": 4.5e11,
                    "estimatedEpsAvg": 7.5,
                    "numberAnalystEstimatedRevenue": 30,
                }
            ],
            "holders": [
                {"holder": "Vanguard", "shares": 1.3e9, "change": 1e7},
                {"holder": "BlackRock", "shares": 1.0e9, "change": -2e6},
            ],
            "ownership": [
                {
                    "date": "2026-06-30",
                    "investorName": "Vanguard",
                    "sharesNumber": 1.3e9,
                    "changeInSharesNumber": 1e7,
                }
            ],
        }
        self.data.update(overrides)
        self.transcript_requests: list[tuple[int, int]] = []

    async def get_company_profile(self, symbol: str) -> dict:
        return self.data["profile"]

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        return self.data["income"][:limit]

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        return self.data["balance"][:limit]

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        return self.data["cash_flow"][:limit]

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        return self.data["key_metrics"]

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        return self.data["ratios"][:limit]

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        return self.data["surprises"]

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        self.transcript_requests.append((year, quarter))
        return self.data["transcripts"].get((year, quarter), {})

    async def get_analyst_estimates(self, symbol: str, limit: int = 8) -> list[dict]:
        return self.data["estimates"]

    async def get_institutional_holders(self, symbol: str) -> list[dict]:
        return self.data["holders"]

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        return self.data["ownership"]


class FakeEdgar:
    def __init__(self, business: str = "", risk: str = "") -> None:
        self.business = business or "Our brand and installed base create switching cost."
        self.risk = risk or "We face litigation and geopolitical risk."

    async def get_business_section(self, symbol: str) -> str:
        return self.business

    async def get_risk_factors(self, symbol: str) -> str:
        return self.risk


class FakeLLM:
    """
    Stands in for the LLMRouter: returns `reply` (dict of fields) validated against
    the requested schema, and records every call (including the provider asked for).
    """

    default_provider = "anthropic"

    def __init__(self, reply: dict | None = None, fail: bool = False) -> None:
        self.reply = reply or {"signal": "bullish", "confidence": 70.0, "reasoning": "LLM says so"}
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        model: str | None = None,
        max_tokens: int = 1024,
        mcp_servers: Any = None,
        prompt_name: str | None = None,
        provider: str | None = None,
    ) -> BaseModel:
        self.calls.append(
            {
                "system": system,
                "prompt": prompt,
                "schema": schema,
                "model": model,
                "mcp_servers": mcp_servers,
                "prompt_name": prompt_name,
                "provider": provider,
                "max_tokens": max_tokens,
            }
        )
        if self.fail:
            raise LLMError("fake outage")
        fields = dict(self.reply)
        if "observations" in schema.model_fields:
            fields.setdefault("observations", ["breakout"])
            fields.setdefault("risk_level", "low")
        return schema.model_validate(fields)

    def default_model(self, provider: str | None = None) -> str:
        return "fake-model"

    async def aclose(self) -> None:
        return None


class FakeResults:
    def __init__(self, results: dict[str, dict] | None = None) -> None:
        self.results = results or {}

    async def get_for_date(self, symbol: str, run_date: date, agent_types: list[str]) -> dict:
        return {k: v for k, v in self.results.items() if k in agent_types}


def make_context(
    *,
    yfinance: Any = None,
    fmp: Any = None,
    edgar: Any = None,
    llm: Any = None,
    results: Any = None,
    profiles: ProfileBook | None = None,
) -> AgentContext:
    return AgentContext(
        yfinance=yfinance or FakeYFinance(),
        fmp=fmp or FakeFmp(),
        edgar=edgar or FakeEdgar(),
        llm=llm or FakeLLM(),
        results=results or FakeResults(),
        reasoning_model="reasoning-model",
        profiles=profiles or ProfileBook(),
    )
