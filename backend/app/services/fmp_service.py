"""
FMP (Financial Modeling Prep) service — all FMP API calls go through here.
Wraps every call with with_retry() for rate limiting and timeout protection.
Never call the FMP API directly from agent or service code.

Base URL: https://financialmodelingprep.com/api/v3/
Free tier: 250 calls/day — use sparingly in development.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.external_api_base import with_retry
from app.services.yfinance_service import validate_symbol

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3"


def _get(path: str, params: dict[str, Any] | None = None) -> list[dict] | dict:
    """
    Synchronous HTTP GET against FMP. Always appends apikey.
    Raises httpx.HTTPStatusError on non-2xx.
    Called exclusively inside with_retry() closures — never directly.
    """
    all_params: dict[str, Any] = {"apikey": settings.fmp_api_key, **(params or {})}
    with httpx.Client(timeout=9.0) as client:
        resp = client.get(f"{_BASE_URL}/{path}", params=all_params)
        resp.raise_for_status()
        return resp.json()


async def get_company_profile(symbol: str) -> dict:
    """
    Fetch company profile: name, description, sector, industry, CEO, market cap.
    Returns empty dict if unavailable.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> dict:
        data = _get(f"profile/{validated}")
        if not data or not isinstance(data, list):
            logger.warning("FMP returned empty profile for %s", validated)
            return {}
        return data[0]

    return await with_retry(_fetch, label=f"fmp.profile({validated})")


async def get_income_statements(symbol: str, limit: int = 5) -> list[dict]:
    """
    Annual income statements for up to `limit` years.
    Key fields: date, revenue, grossProfit, operatingIncome, netIncome, ebitda, eps.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"income-statement/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            logger.warning("FMP income statements unexpected format for %s", validated)
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.income_statements({validated})")


async def get_balance_sheets(symbol: str, limit: int = 5) -> list[dict]:
    """
    Annual balance sheets for up to `limit` years.
    Key fields: date, totalDebt, cashAndCashEquivalents, totalStockholdersEquity,
                goodwillAndIntangibleAssets, totalAssets, totalLiabilities.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"balance-sheet-statement/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.balance_sheets({validated})")


async def get_cash_flow_statements(symbol: str, limit: int = 5) -> list[dict]:
    """
    Annual cash flow statements for up to `limit` years.
    Key fields: date, freeCashFlow, operatingCashFlow, capitalExpenditure, dividendsPaid.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"cash-flow-statement/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.cash_flow({validated})")


async def get_key_metrics(symbol: str, limit: int = 5) -> list[dict]:
    """
    Annual key metrics for up to `limit` years.
    Key fields: date, peRatio, pbRatio, evToEbitda, roe, roic, debtToEquity,
                enterpriseValue, freeCashFlowPerShare, dividendYield.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"key-metrics/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.key_metrics({validated})")


async def get_financial_ratios(symbol: str, limit: int = 5) -> list[dict]:
    """
    Annual financial ratios for up to `limit` years.
    Key fields: date, grossProfitMargin, operatingProfitMargin, netProfitMargin,
                returnOnEquity, returnOnAssets, debtRatio, interestCoverage.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"ratios/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.ratios({validated})")


async def get_earnings_surprises(symbol: str) -> list[dict]:
    """
    Historical earnings surprises (actual vs estimated EPS).
    Key fields: date, actualEarningResult, estimatedEarning.
    Derive: surprise_pct = (actual - estimate) / abs(estimate) * 100
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(f"earnings-surprises/{validated}")
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.earnings_surprises({validated})")


async def get_earnings_call_transcript(symbol: str, year: int, quarter: int) -> dict:
    """
    Earnings call transcript for a specific quarter.
    Key fields: symbol, quarter, year, date, content.
    Content is truncated to 15,000 chars to fit LLM context.
    Returns empty dict if transcript unavailable (common for small-caps).
    """
    validated = validate_symbol(symbol)

    def _fetch() -> dict:
        data = _get(
            f"earning_call_transcript/{validated}",
            params={"year": year, "quarter": quarter},
        )
        if not data:
            return {}
        item = data[0] if isinstance(data, list) else data
        # Truncate long transcripts to avoid LLM context overflow
        if isinstance(item.get("content"), str):
            item["content"] = item["content"][:15000]
        return item

    return await with_retry(_fetch, label=f"fmp.transcript({validated}, {year}Q{quarter})")


async def get_analyst_estimates(symbol: str, limit: int = 8) -> list[dict]:
    """
    Analyst consensus estimates (forward-looking revenue and EPS).
    Key fields: date, estimatedRevenueAvg, estimatedEpsAvg,
                estimatedRevenueLow, estimatedRevenueHigh,
                numberAnalystEstimatedRevenue, numberAnalystsEstimatedEps.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            f"analyst-estimates/{validated}",
            params={"limit": limit, "period": "annual"},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.analyst_estimates({validated})")


async def get_institutional_holders(symbol: str) -> list[dict]:
    """
    Current institutional holders (top ~50 by shares).
    Key fields: holder, shares, dateReported, change, weightPercent.
    Positive change = accumulating, negative = distributing.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(f"institutional-holder/{validated}")
        if not isinstance(data, list):
            return []
        # Sort by shares descending, return top 50
        return sorted(data, key=lambda x: x.get("shares", 0), reverse=True)[:50]

    return await with_retry(_fetch, label=f"fmp.institutional_holders({validated})")


async def get_13f_institutional_ownership(symbol: str, limit: int = 4) -> list[dict]:
    """
    Quarterly 13F institutional ownership snapshots (last `limit` quarters).
    Key fields: date, investorName, sharesNumber, marketValue,
                changeInSharesNumber, changeInWeightPercent.
    Use to detect accumulation/distribution trend over time.
    """
    validated = validate_symbol(symbol)

    def _fetch() -> list[dict]:
        data = _get(
            "institutional-ownership/symbol-ownership",
            params={"symbol": validated, "limit": limit},
        )
        if not isinstance(data, list):
            return []
        return data

    return await with_retry(_fetch, label=f"fmp.13f_ownership({validated})")
