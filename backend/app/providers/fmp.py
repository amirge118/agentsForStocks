"""
Financial Modeling Prep client, on FMP's current API:
https://financialmodelingprep.com/stable/<endpoint>?symbol=AAPL

(The old /api/v3/ endpoints only serve subscriptions from before 31 Aug 2025.)

The free tier allows 250 calls/day, so every real (uncached) request is counted
against a daily budget: a warning at 80%, QuotaExceededError once it is spent.
Endpoints the plan doesn't include answer HTTP 402; they return no data (with
one warning per endpoint) so the agent runs on with a data gap instead of failing.
On the free plan that is: earnings-call transcripts and institutional ownership,
and `earnings` only up to limit=5.
"""

import logging
from datetime import date
from typing import Any

from app.core.clock import market_today
from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.errors import ProviderError, QuotaExceededError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/stable"
_TRANSCRIPT_MAX_CHARS = 15_000
_NOT_IN_PLAN = 402
# The free plan caps `limit` at 5 on some endpoints (earnings)
_FREE_PLAN_MAX_LIMIT = 5


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
        self._not_in_plan: set[str] = set()

    async def _get(self, path: str, symbol: str, **params: Any) -> Any:
        """GET /stable/<path>?symbol=...; None when the endpoint isn't in the plan."""
        try:
            return await self._http.get_json(
                f"{_BASE_URL}/{path}",
                params={"symbol": validate_symbol(symbol), **params, "apikey": self._api_key},
                on_request=self._budget.consume,  # cache hits are free
            )
        except ProviderError as exc:
            if exc.status != _NOT_IN_PLAN:
                raise
            if path not in self._not_in_plan:
                self._not_in_plan.add(path)
                logger.warning("FMP endpoint not in your plan — no data", extra={"path": path})
            return None

    async def _get_list(self, path: str, symbol: str, **params: Any) -> list[dict]:
        data = await self._get(path, symbol, **params)
        if data is None:
            return []
        if not isinstance(data, list):
            logger.warning("FMP %s returned unexpected payload", path)
            return []
        return data

    async def get_company_profile(self, symbol: str) -> dict:
        """companyName, description, sector, industry, ceo, marketCap, isEtf, ipoDate."""
        rows = await self._get_list("profile", symbol)
        return rows[0] if rows else {}

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual, most recent first: revenue, grossProfit, operatingIncome, netIncome, ebitda."""
        return await self._get_list("income-statement", symbol, limit=limit, period="annual")

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: totalDebt, cashAndCashEquivalents, totalStockholdersEquity, totalAssets."""
        return await self._get_list("balance-sheet-statement", symbol, limit=limit, period="annual")

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: freeCashFlow, operatingCashFlow, capitalExpenditure."""
        return await self._get_list("cash-flow-statement", symbol, limit=limit, period="annual")

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: evToEBITDA, currentRatio, enterpriseValue, returnOnEquity, marketCap."""
        return await self._get_list("key-metrics", symbol, limit=limit, period="annual")

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: grossProfitMargin, netProfitMargin, debtToEquityRatio, priceToEarningsRatio."""
        return await self._get_list("ratios", symbol, limit=limit, period="annual")

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        """date, epsActual, epsEstimated, revenueActual, revenueEstimated — most recent first.
        The next (upcoming) report comes first, with epsActual = None."""
        return await self._get_list("earnings", symbol, limit=_FREE_PLAN_MAX_LIMIT)

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        """quarter, year, date, content (truncated). {} when unavailable or not in the plan."""
        data = await self._get("earning-call-transcript", symbol, year=year, quarter=quarter)
        item = data[0] if isinstance(data, list) and data else data
        if not isinstance(item, dict) or not item:
            return {}
        content = item.get("content")
        if isinstance(content, str):
            item = {**item, "content": content[:_TRANSCRIPT_MAX_CHARS]}
        return item

    async def get_analyst_estimates(self, symbol: str, limit: int = 8) -> list[dict]:
        """Forward estimates: revenueAvg, epsAvg, numAnalystsRevenue, numAnalystsEps."""
        return await self._get_list("analyst-estimates", symbol, limit=limit, period="annual")

    async def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Top 50 holders by shares: holder, shares, change. Not in the free plan ([])."""
        rows = await self._get_list("institutional-ownership/extract-analytics/holder", symbol)
        return sorted(rows, key=lambda r: r.get("shares") or 0, reverse=True)[:50]

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        """Quarterly 13F summaries. Not in the free plan ([])."""
        return await self._get_list(
            "institutional-ownership/symbol-positions-summary", symbol, limit=limit
        )
