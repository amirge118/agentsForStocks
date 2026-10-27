"""
Financial Modeling Prep client. Base URL: https://financialmodelingprep.com/stable/
(the /api/v3 endpoints answer 403 for keys issued after August 2025).

The stable API renamed some fields; rows are returned under the names the agents
read (the old v3 names), next to the new ones, so callers don't depend on the version.

The free tier allows 250 calls/day, so every real (uncached) request is counted
against a daily budget: a warning at 80%, QuotaExceededError once it is spent.
Endpoints outside the plan (transcripts, 13F on the free tier) answer 402 and
come back empty, like any other missing data.
"""

import logging
from datetime import date, timedelta
from typing import Any

from app.core.clock import market_today
from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.errors import PlanRestrictedError, QuotaExceededError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/stable"
_TRANSCRIPT_MAX_CHARS = 15_000
_EARNINGS_LIMIT = 5  # the free plan answers 402 to a larger `limit`
_13F_FILING_DAYS = 45  # 13F reports are due 45 days after the quarter ends

# stable field → v3 field the agents read
_PROFILE_FIELDS = {"marketCap": "mktCap"}
_EARNINGS_FIELDS = {"epsActual": "actualEarningResult", "epsEstimated": "estimatedEarning"}
_ESTIMATE_FIELDS = {
    "revenueAvg": "estimatedRevenueAvg",
    "epsAvg": "estimatedEpsAvg",
    "numAnalystsRevenue": "numberAnalystEstimatedRevenue",
    "numAnalystsEps": "numberAnalystsEstimatedEps",
}
_RATIO_FIELDS = {"debtToEquityRatio": "debtToEquity"}
_HOLDER_FIELDS = {
    "investorName": "holder",
    "sharesNumber": "shares",
    "changeInSharesNumber": "change",
    "filingDate": "dateReported",
}


def _with_v3_names(row: dict, fields: dict[str, str]) -> dict:
    return {**row, **{old: row[new] for new, old in fields.items() if new in row}}


def latest_13f_quarter(today: date) -> tuple[int, int]:
    """(year, quarter) of the most recent quarter whose 13F filing deadline has passed."""
    cutoff = today - timedelta(days=_13F_FILING_DAYS)
    quarter = (cutoff.month - 1) // 3  # the quarter before the one `cutoff` falls in
    return (cutoff.year, quarter) if quarter else (cutoff.year - 1, 4)


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

    async def _get_list_in_plan(self, path: str, **params: Any) -> list[dict]:
        """Like _get_list, but an endpoint the plan doesn't include is just no data."""
        try:
            return await self._get_list(path, **params)
        except PlanRestrictedError:
            logger.warning("FMP %s is not included in the current plan", path)
            return []

    async def get_company_profile(self, symbol: str) -> dict:
        """companyName, description, sector, industry, ceo, mktCap, fullTimeEmployees, ipoDate."""
        rows = await self._get_list("profile", symbol=validate_symbol(symbol))
        return _with_v3_names(rows[0], _PROFILE_FIELDS) if rows else {}

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual, most recent first: revenue, grossProfit, operatingIncome, netIncome, ebitda."""
        return await self._get_list(
            "income-statement", symbol=validate_symbol(symbol), limit=limit, period="annual"
        )

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: totalDebt, cashAndCashEquivalents, totalStockholdersEquity, totalAssets."""
        return await self._get_list(
            "balance-sheet-statement", symbol=validate_symbol(symbol), limit=limit, period="annual"
        )

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: freeCashFlow, operatingCashFlow, capitalExpenditure."""
        return await self._get_list(
            "cash-flow-statement", symbol=validate_symbol(symbol), limit=limit, period="annual"
        )

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: debtToEquity, currentRatio, returnOnEquity, evToEBITDA, enterpriseValue."""
        return await self._annual_ratios(symbol, limit)

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: grossProfitMargin, operatingProfitMargin, netProfitMargin, returnOnEquity."""
        return await self._annual_ratios(symbol, limit)

    async def _annual_ratios(self, symbol: str, limit: int) -> list[dict]:
        """
        The stable API moved fields between the two endpoints (returnOnEquity to
        key-metrics, debt/equity to ratios), so both methods return the ratio rows
        merged with the key-metrics row of the same year. Same calls for both: cached.
        """
        ticker = validate_symbol(symbol)
        ratios = await self._get_list("ratios", symbol=ticker, limit=limit, period="annual")
        metrics_rows = await self._get_list(
            "key-metrics", symbol=ticker, limit=limit, period="annual"
        )
        by_date = {row.get("date"): row for row in metrics_rows}
        return [
            _with_v3_names({**by_date.get(row.get("date"), {}), **row}, _RATIO_FIELDS)
            for row in ratios
        ]

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        """Reported quarters, most recent first: date, actualEarningResult, estimatedEarning."""
        rows = await self._get_list(
            "earnings", symbol=validate_symbol(symbol), limit=_EARNINGS_LIMIT
        )
        # The list starts with the upcoming report, which has no actual EPS yet
        return [_with_v3_names(r, _EARNINGS_FIELDS) for r in rows if r.get("epsActual") is not None]

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        """quarter, year, date, content (truncated). {} when unavailable."""
        rows = await self._get_list_in_plan(
            "earning-call-transcript", symbol=validate_symbol(symbol), year=year, quarter=quarter
        )
        item = rows[0] if rows else {}
        if not isinstance(item, dict) or not item:
            return {}
        item = {"quarter": quarter, "year": year, **item}
        content = item.get("content")
        if isinstance(content, str):
            item = {**item, "content": content[:_TRANSCRIPT_MAX_CHARS]}
        return item

    async def get_analyst_estimates(self, symbol: str, limit: int = 8) -> list[dict]:
        """Forward estimates: estimatedRevenueAvg, estimatedEpsAvg, analyst counts."""
        rows = await self._get_list(
            "analyst-estimates", symbol=validate_symbol(symbol), limit=limit, period="annual"
        )
        return [_with_v3_names(r, _ESTIMATE_FIELDS) for r in rows]

    async def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Top 50 holders by shares in the latest 13F quarter: holder, shares, change."""
        rows = await self._latest_13f_holders(symbol)
        return sorted(rows, key=lambda r: r.get("shares") or 0, reverse=True)[:50]

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        """Latest 13F quarter, largest holders first: date, investorName, sharesNumber,
        changeInSharesNumber. Same request as get_institutional_holders (cached)."""
        return (await self.get_institutional_holders(symbol))[:limit]

    async def _latest_13f_holders(self, symbol: str) -> list[dict]:
        year, quarter = latest_13f_quarter(market_today())
        rows = await self._get_list_in_plan(
            "institutional-ownership/extract-analytics/holder",
            symbol=validate_symbol(symbol),
            year=year,
            quarter=quarter,
            limit=100,
        )
        return [_with_v3_names(r, _HOLDER_FIELDS) for r in rows]
