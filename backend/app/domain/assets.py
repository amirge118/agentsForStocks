"""
What kind of security a symbol is. A fund (ETF, mutual fund) has no 10-K,
income statement, earnings call or moat of its own, so the company-only agents
(@register_agent(company_only=True)) don't run for it: their result would be a
company analysis of something that isn't a company.

The kind comes from `quoteType` in Ticker.info — set by yfinance, by the Yahoo
chart fallback (instrumentType) or by FMP's profile (isEtf / isFund).
"""

from typing import Any

FUND_QUOTE_TYPES = frozenset({"ETF", "MUTUALFUND"})


def is_fund(info: dict[str, Any]) -> bool:
    """True for an ETF or mutual fund; unknown counts as a company (every agent runs)."""
    return str(info.get("quoteType") or "").upper() in FUND_QUOTE_TYPES
