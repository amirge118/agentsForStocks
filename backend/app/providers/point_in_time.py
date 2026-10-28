"""
Point-in-time providers: what the data sources knew on a past day, for historical
runs (backtests, reruns of a past date). Wrapped around the live clients by
AgentRunner when the orchestrator runs a date before today; a live run never sees them.

Three kinds of data, three rules:
  dated history   kept up to `as_of` — prices to that close, statements by filing
                  date, the 10-K filed by then, earnings reported before it, insider
                  trades and news dated on or before it;
  period data     without a filing date (ratios, key metrics, 13F summaries) kept once
                  the period ended long enough ago to have been reported;
  live snapshots  withheld — `info`, the profile's market fields, current holders,
                  analyst estimates. They describe today, not `as_of`; they come back
                  empty, so the agent's contract lists them as data gaps and the model
                  is told they are missing.

Known limit: adjusted prices are back-adjusted for splits and dividends paid after
`as_of`. Levels shift; returns, trends and indicators don't.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from app.providers.edgar import EdgarClient
from app.providers.fmp import FREE_PLAN_MAX_LIMIT, FmpClient
from app.providers.yfinance import YFinanceClient

logger = logging.getLogger(__name__)

# 10-K: 60-90 days after the fiscal year end; a period counts as reported after this
REPORTING_LAG = timedelta(days=90)
# 13F: 45 days after the quarter end
THIRTEEN_F_LAG = timedelta(days=45)
# Profile fields that describe the market today, not the company
LIVE_PROFILE_FIELDS = frozenset(
    {
        "price",
        "marketCap",
        "mktCap",
        "beta",
        "lastDividend",
        "lastDiv",
        "range",
        "change",
        "changes",
        "changePercentage",
        "volume",
        "averageVolume",
        "volAvg",
        "dcf",
        "dcfDiff",
    }
)
# yfinance periods, shortest first, with the calendar days each covers
_PERIODS: tuple[tuple[str, int], ...] = (
    ("1mo", 31),
    ("3mo", 92),
    ("6mo", 183),
    ("1y", 366),
    ("2y", 731),
    ("5y", 1827),
    ("10y", 3653),
)
_PERIOD_DAYS = dict(_PERIODS) | {"1d": 1, "5d": 7}


def _day(value: Any) -> date | None:
    """A date from a date, a datetime, a Timestamp or an ISO-like string; None otherwise."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):  # epoch seconds (yfinance news)
        return datetime.fromtimestamp(value, UTC).date()
    try:
        return pd.Timestamp(str(value)).date()
    except (ValueError, TypeError):
        return None


def known_by(rows: list[dict], as_of: date, *keys: str, lag: timedelta = timedelta()) -> list:
    """Rows whose first present date field, plus `lag`, is on or before `as_of`."""
    kept = []
    for row in rows:
        stamp = next((d for k in keys if (d := _day(row.get(k))) is not None), None)
        if stamp is not None and stamp + lag <= as_of:
            kept.append(row)
    return kept


def covering_period(as_of: date, period: str, today: date) -> str:
    """The shortest yfinance period that reaches back `period` before `as_of` from today."""
    needed = (today - as_of).days + _PERIOD_DAYS.get(period, 366)
    return next((name for name, days in _PERIODS if days >= needed), "max")


class PointInTimeYFinance:
    def __init__(self, inner: YFinanceClient, as_of: date, today: date) -> None:
        self._inner = inner
        self.as_of = as_of
        self._today = today

    async def get_info(self, symbol: str) -> dict:
        return {}  # a snapshot of today

    async def get_history(
        self, symbol: str, period: str = "1mo", interval: str = "1d"
    ) -> pd.DataFrame:
        wide = covering_period(self.as_of, period, self._today)
        df = await self._inner.get_history(symbol, period=wide, interval=interval)
        if df.empty:
            return df
        days = pd.DatetimeIndex(df.index)
        days = (days.tz_localize(None) if days.tz is not None else days).normalize()
        start = pd.Timestamp(self.as_of) - pd.Timedelta(days=_PERIOD_DAYS.get(period, 366))
        return df[(days > start) & (days <= pd.Timestamp(self.as_of))]

    async def get_closes(self, symbol: str, start: date, end: date) -> pd.Series:
        return await self._inner.get_closes(symbol, start, min(end, self.as_of + timedelta(1)))

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        df = await self._inner.get_earnings_dates(symbol)
        if df.empty:
            return df
        days = pd.DatetimeIndex(df.index)
        days = days.tz_localize(None) if days.tz is not None else days
        # Reported before the day: an after-close report on `as_of` wasn't known yet
        return df[days.normalize() < pd.Timestamp(self.as_of)]

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        rows = await self._inner.get_insider_transactions(symbol)
        return known_by(rows, self.as_of, "Start Date", "Date")

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        # Yahoo serves only its latest headlines: for a past day this is usually empty,
        # which is the truth — the feed can't reach that window
        items = await self._inner.get_news(symbol, count=count)
        return [i for i in items if (d := _news_day(i)) is not None and d <= self.as_of]


def _news_day(item: dict) -> date | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    return _day(
        item.get("providerPublishTime") or content.get("pubDate") or content.get("displayTime")
    )


class PointInTimeFmp:
    def __init__(self, inner: FmpClient, as_of: date) -> None:
        self._inner = inner
        self.as_of = as_of

    async def get_company_profile(self, symbol: str) -> dict:
        profile = await self._inner.get_company_profile(symbol)
        return {k: v for k, v in profile.items() if k not in LIVE_PROFILE_FIELDS}

    def _filed(self, rows: list[dict], limit: int) -> list[dict]:
        return known_by(rows, self.as_of, "filingDate", "acceptedDate")[:limit]

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        rows = await self._inner.get_income_statements(symbol, limit=_wider(limit))
        return self._filed(rows, limit)

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        rows = await self._inner.get_balance_sheets(symbol, limit=_wider(limit))
        return self._filed(rows, limit)

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        rows = await self._inner.get_cash_flow_statements(symbol, limit=_wider(limit))
        return self._filed(rows, limit)

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        rows = await self._inner.get_key_metrics(symbol, limit=_wider(limit))
        return known_by(rows, self.as_of, "date", lag=REPORTING_LAG)[:limit]

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        rows = await self._inner.get_financial_ratios(symbol, limit=_wider(limit))
        return known_by(rows, self.as_of, "date", lag=REPORTING_LAG)[:limit]

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        rows = await self._inner.get_earnings_surprises(symbol)
        return [r for r in rows if (d := _day(r.get("date"))) is not None and d < self.as_of]

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        item = await self._inner.get_earnings_call_transcript(symbol, year, quarter)
        day = _day(item.get("date"))
        return item if day is not None and day <= self.as_of else {}

    async def get_analyst_estimates(self, symbol: str, limit: int = 8) -> list[dict]:
        return []  # revised every day: today's numbers, not those of `as_of`

    async def get_institutional_holders(self, symbol: str) -> list[dict]:
        return []  # today's holders

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        rows = await self._inner.get_13f_institutional_ownership(symbol, limit=_wider(limit))
        return known_by(rows, self.as_of, "date", lag=THIRTEEN_F_LAG)[:limit]

    async def get_info_fields(self, symbol: str) -> dict[str, Any]:
        return {}  # built from today's TTM figures


class PointInTimeEdgar:
    def __init__(self, inner: EdgarClient, as_of: date) -> None:
        self._inner = inner
        self.as_of = as_of

    async def get_business_section(self, symbol: str) -> str:
        return await self._inner.get_10k_section(symbol, "business", filed_by=self.as_of)

    async def get_risk_factors(self, symbol: str) -> str:
        return await self._inner.get_10k_section(symbol, "risk_factors", filed_by=self.as_of)

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        rows = await self._inner.get_insider_transactions(symbol, filed_by=self.as_of)
        return known_by(rows, self.as_of, "Start Date")

    async def get_earnings_release(self, symbol: str) -> dict:
        return await self._inner.get_earnings_release(symbol, filed_by=self.as_of)


# Ask for a few more rows than needed: the newest may be filtered out as not yet filed.
# Never above the free plan's cap, which answers a larger limit with no data at all.
_EXTRA = 3


def _wider(limit: int) -> int:
    return max(limit, min(limit + _EXTRA, FREE_PLAN_MAX_LIMIT))
