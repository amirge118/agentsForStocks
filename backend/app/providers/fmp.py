"""
Financial Modeling Prep client. Base URL: https://financialmodelingprep.com/api/v3/

The free tier allows 250 calls/day, so every real (uncached) request is counted
against a daily budget: a warning at 80%, QuotaExceededError once it is spent.
"""

import logging
from datetime import date
from typing import Any

from app.core.clock import market_today
from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.errors import QuotaExceededError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3"
_TRANSCRIPT_MAX_CHARS = 15_000


class DailyCallBudget:
    def __init__(self, limit: int, warn_ratio: float = 0.8) -> None:
        self.limit = limit
        self._warn_at = int(limit * warn_ratio)
        self._day: date | None = None
        self.used = 0

    def consume(self) -> None:
        today = market_today()
        if today != self._day:
            self._day, self.used = today, 0
        if self.used >= self.limit:
            raise QuotaExceededError(f"FMP daily budget of {self.limit} calls exhausted")
        self.used += 1
        metrics.fmp_calls.add(1)
        if self.used == self._warn_at:
            logger.warning("FMP daily budget at %d/%d calls", self.used, self.limit)


class FmpClient:
    def __init__(self, http: HttpClient, api_key: str, budget: DailyCallBudget) -> None:
        self._http = http
        self._api_key = api_key
        self._budget = budget

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._http.get_json(
            f"{_BASE_URL}/{path}",
            params={**params, "apikey": self._api_key},
            on_request=self._budget.consume,  # cache hits are free
        )

    async def _get_list(self, path: str, **params: Any) -> list[dict]:
        data = await self._get(path, **params)
        if not isinstance(data, list):
            logger.warning("FMP %s returned unexpected payload", path)
            return []
        return data

    async def get_company_profile(self, symbol: str) -> dict:
        """name, description, sector, industry, ceo, mktCap, fullTimeEmployees, ipoDate."""
        rows = await self._get_list(f"profile/{validate_symbol(symbol)}")
        return rows[0] if rows else {}

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual, most recent first: revenue, grossProfit, operatingIncome, netIncome, ebitda."""
        return await self._get_list(
            f"income-statement/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: totalDebt, cashAndCashEquivalents, totalStockholdersEquity, totalAssets."""
        return await self._get_list(
            f"balance-sheet-statement/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: freeCashFlow, operatingCashFlow, capitalExpenditure."""
        return await self._get_list(
            f"cash-flow-statement/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: peRatio, evToEbitda, debtToEquity, currentRatio, enterpriseValue."""
        return await self._get_list(
            f"key-metrics/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: grossProfitMargin, operatingProfitMargin, netProfitMargin, returnOnEquity."""
        return await self._get_list(
            f"ratios/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        """date, actualEarningResult, estimatedEarning — most recent first."""
        return await self._get_list(f"earnings-surprises/{validate_symbol(symbol)}")

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        """quarter, year, date, content (truncated). {} when unavailable."""
        data = await self._get(
            f"earning_call_transcript/{validate_symbol(symbol)}", year=year, quarter=quarter
        )
        item = data[0] if isinstance(data, list) and data else data
        if not isinstance(item, dict) or not item:
            return {}
        content = item.get("content")
        if isinstance(content, str):
            item = {**item, "content": content[:_TRANSCRIPT_MAX_CHARS]}
        return item

    async def get_analyst_estimates(self, symbol: str, limit: int = 8) -> list[dict]:
        """Forward estimates: estimatedRevenueAvg, estimatedEpsAvg, analyst counts."""
        return await self._get_list(
            f"analyst-estimates/{validate_symbol(symbol)}", limit=limit, period="annual"
        )

    async def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Top 50 holders by shares: holder, shares, change, dateReported."""
        rows = await self._get_list(f"institutional-holder/{validate_symbol(symbol)}")
        return sorted(rows, key=lambda r: r.get("shares") or 0, reverse=True)[:50]

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        """Quarterly 13F snapshots: date, investorName, sharesNumber, changeInSharesNumber."""
        return await self._get_list(
            "institutional-ownership/symbol-ownership", symbol=validate_symbol(symbol), limit=limit
        )
