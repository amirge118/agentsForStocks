"""
Financial Modeling Prep client, on FMP's current API:
https://financialmodelingprep.com/stable/<endpoint>?symbol=AAPL

(The old /api/v3/ endpoints only serve subscriptions from before 31 Aug 2025.)

The free tier allows 250 calls/day, so every real (uncached) request is counted
against a daily budget: a warning at 80%, QuotaExceededError once it is spent.
The count is kept in the database (provider_calls) when a counter is given, so a
restart or a second process (API + worker) can't reset it and overrun the plan.
Endpoints the plan doesn't include answer HTTP 402; they return no data (with
one warning per endpoint) so the agent runs on with a data gap instead of failing.
On the free plan that is: earnings-call transcripts and institutional ownership,
and `earnings` only up to limit=5.
"""

import asyncio
import logging
from datetime import date
from typing import Any, Protocol

from app.core.clock import market_today
from app.core.symbols import validate_symbol
from app.observability import metrics
from app.providers.errors import ProviderError, QuotaExceededError
from app.providers.http import HttpClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/stable"
_TRANSCRIPT_MAX_CHARS = 15_000
_NOT_IN_PLAN = 402
# The free plan rejects `limit` above 5 (HTTP 402) on the statement and earnings endpoints
FREE_PLAN_MAX_LIMIT = 5


class CallCounter(Protocol):
    async def increment(self, day: date) -> int:
        """Count one call on `day`; return the day's total across every process."""
        ...


class DailyCallBudget:
    def __init__(
        self, limit: int, warn_ratio: float = 0.8, counter: CallCounter | None = None
    ) -> None:
        self.limit = limit
        self._warn_at = int(limit * warn_ratio)
        self._counter = counter
        self._day: date | None = None
        self.used = 0

    async def consume(self) -> None:
        today = market_today()
        if today != self._day:
            self._day, self.used = today, 0
        if self.used >= self.limit:
            raise QuotaExceededError(f"FMP daily budget of {self.limit} calls exhausted")
        before = self.used
        self.used = await self._count(today)
        if self.used > self.limit:  # another process spent the last calls
            raise QuotaExceededError(f"FMP daily budget of {self.limit} calls exhausted")
        metrics.fmp_calls.add(1)
        if before < self._warn_at <= self.used:
            logger.warning("FMP daily budget at %d/%d calls", self.used, self.limit)

    async def _count(self, day: date) -> int:
        """The stored total; this process's own count when the database can't answer."""
        if self._counter is not None:
            try:
                return await self._counter.increment(day)
            except Exception as exc:
                logger.warning("FMP call count not stored", extra={"error": str(exc)})
        return self.used + 1


class FmpClient:
    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        budget: DailyCallBudget,
        *,
        statement_rows: int = FREE_PLAN_MAX_LIMIT,
        earnings_limit: int = FREE_PLAN_MAX_LIMIT,
    ) -> None:
        """
        statement_rows: annual rows fetched per statement endpoint, whatever `limit` an
        agent asks for — one cached call per symbol and endpoint instead of one per
        limit. earnings_limit: rows of `earnings` (the free plan stops at 5).
        """
        self._http = http
        self._api_key = api_key
        self._budget = budget
        self._statement_rows = statement_rows
        self._earnings_limit = earnings_limit
        self._not_in_plan: set[str] = set()

    async def _get(self, path: str, symbol: str, **params: Any) -> Any:
        """GET /stable/<path>?symbol=...; None when the endpoint isn't in the plan."""
        if path in self._not_in_plan:  # known since its first 402: don't spend a call on it
            return None
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

    async def _annual(self, path: str, symbol: str, limit: int) -> list[dict]:
        """The latest `limit` annual rows, from one shared request of `statement_rows`."""
        rows = await self._get_list(
            path, symbol, limit=max(limit, self._statement_rows), period="annual"
        )
        return rows[:limit]

    async def get_company_profile(self, symbol: str) -> dict:
        """companyName, description, sector, industry, ceo, marketCap, isEtf, ipoDate."""
        rows = await self._get_list("profile", symbol)
        return rows[0] if rows else {}

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual, most recent first: revenue, grossProfit, operatingIncome, netIncome, ebitda."""
        return await self._annual("income-statement", symbol, limit)

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: totalDebt, cashAndCashEquivalents, totalStockholdersEquity, totalAssets."""
        return await self._annual("balance-sheet-statement", symbol, limit)

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: freeCashFlow, operatingCashFlow, capitalExpenditure."""
        return await self._annual("cash-flow-statement", symbol, limit)

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: evToEBITDA, currentRatio, enterpriseValue, returnOnEquity, marketCap."""
        return await self._annual("key-metrics", symbol, limit)

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        """Annual: grossProfitMargin, netProfitMargin, debtToEquityRatio, priceToEarningsRatio."""
        return await self._annual("ratios", symbol, limit)

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        """date, epsActual, epsEstimated, revenueActual, revenueEstimated — most recent first.
        The next (upcoming) report comes first, with epsActual = None."""
        return await self._get_list("earnings", symbol, limit=self._earnings_limit)

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

    async def get_info_fields(self, symbol: str) -> dict[str, Any]:
        """
        yfinance-style `info` fundamentals built from FMP (see to_info_fields) — for
        when Yahoo only returns a quote. Six calls, all cached and shared with the
        agents (every statement endpoint is fetched once per symbol).
        """
        profile, ratios, metrics, income, balance, cash_flow = await asyncio.gather(
            self.get_company_profile(symbol),
            self.get_financial_ratios(symbol, limit=1),
            self.get_key_metrics(symbol, limit=1),
            self.get_income_statements(symbol, limit=2),
            self.get_balance_sheets(symbol, limit=1),
            self.get_cash_flow_statements(symbol, limit=1),
        )
        return to_info_fields(profile, ratios, metrics, income, balance, cash_flow)


def _first(rows: list[dict]) -> dict:
    return rows[0] if rows else {}


def _growth(new: Any, old: Any) -> float | None:
    if not isinstance(new, int | float) or not isinstance(old, int | float) or old <= 0:
        return None
    return new / old - 1


def to_info_fields(
    profile: dict,
    ratios: list[dict],
    metrics: list[dict],
    income: list[dict],
    balance: list[dict],
    cash_flow: list[dict],
) -> dict[str, Any]:
    """
    FMP's stable fields under the names yfinance's Ticker.info uses, so the agents
    read one vocabulary. Units follow yfinance: debtToEquity in percent (FMP gives
    a ratio), margins and growth as fractions. Growth is annual year over year
    (yfinance's is quarterly). Missing values are left out, never set to 0.
    """
    r, m, cf, b = _first(ratios), _first(metrics), _first(cash_flow), _first(balance)
    latest, previous = _first(income), _first(income[1:])
    de = r.get("debtToEquityRatio")
    fields: dict[str, Any] = {
        "longName": profile.get("companyName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "marketCap": profile.get("marketCap"),
        "beta": profile.get("beta"),
        "averageVolume": profile.get("averageVolume"),
        "returnOnEquity": m.get("returnOnEquity"),
        "enterpriseValue": m.get("enterpriseValue"),
        "profitMargins": r.get("netProfitMargin"),
        "operatingMargins": r.get("operatingProfitMargin"),
        "grossMargins": r.get("grossProfitMargin"),
        "currentRatio": r.get("currentRatio"),
        "debtToEquity": de * 100 if isinstance(de, int | float) else None,
        "trailingPE": r.get("priceToEarningsRatio"),
        "priceToBook": r.get("priceToBookRatio"),
        "priceToSalesTrailing12Months": r.get("priceToSalesRatio"),
        "bookValue": r.get("bookValuePerShare"),
        "revenueGrowth": _growth(latest.get("revenue"), previous.get("revenue")),
        "earningsGrowth": _growth(latest.get("netIncome"), previous.get("netIncome")),
        "ebitda": latest.get("ebitda"),
        "operatingIncome": latest.get("operatingIncome"),
        "netIncomeToCommon": latest.get("netIncome"),
        "sharesOutstanding": latest.get("weightedAverageShsOutDil"),
        "totalDebt": b.get("totalDebt"),
        "totalCash": b.get("cashAndShortTermInvestments"),
        "freeCashflow": cf.get("freeCashFlow"),
        "depreciation": cf.get("depreciationAndAmortization"),
        "capitalExpenditures": cf.get("capitalExpenditure"),
        "quoteType": _quote_type(profile),
    }
    return {k: v for k, v in fields.items() if v is not None}


def _quote_type(profile: dict) -> str | None:
    """yfinance's quoteType from FMP's profile flags (None when the profile is empty)."""
    if not profile:
        return None
    if profile.get("isEtf"):
        return "ETF"
    return "MUTUALFUND" if profile.get("isFund") else "EQUITY"
