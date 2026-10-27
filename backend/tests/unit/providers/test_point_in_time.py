from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.providers.point_in_time import (
    LIVE_PROFILE_FIELDS,
    PointInTimeEdgar,
    PointInTimeFmp,
    PointInTimeYFinance,
    covering_period,
    known_by,
)
from tests.factories import FakeEdgar

AS_OF = date(2026, 6, 15)
TODAY = date(2026, 10, 27)


class _YF:
    def __init__(self) -> None:
        self.asked: list = []
        index = pd.bdate_range("2025-01-02", "2026-10-26", tz="America/New_York")
        self.history = pd.DataFrame({"Close": range(len(index))}, index=index, dtype=float)

    async def get_info(self, symbol: str) -> dict:
        return {"marketCap": 4e12}

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d"):
        self.asked.append(("history", period))
        return self.history

    async def get_closes(self, symbol: str, start: date, end: date) -> pd.Series:
        self.asked.append(("closes", start, end))
        return pd.Series(dtype=float)

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        index = pd.DatetimeIndex(["2026-07-30 16:30", "2026-06-15 16:30", "2026-04-30 16:30"])
        return pd.DataFrame({"Reported EPS": [1.9, 1.7, 1.6]}, index=index.tz_localize("UTC"))

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        return [
            {"Start Date": pd.Timestamp("2026-06-10"), "Transaction": "Sale"},
            {"Start Date": pd.Timestamp("2026-07-01"), "Transaction": "Purchase"},
            {"Transaction": "undated"},
        ]

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        published = int(datetime(2026, 6, 14, 12, tzinfo=UTC).timestamp())
        return [
            {"title": "old", "providerPublishTime": published},
            {"title": "new", "content": {"pubDate": "2026-10-20T10:00:00Z"}},
            {"title": "undated"},
        ]


@pytest.mark.unit
async def test_yfinance_serves_only_what_was_known() -> None:
    inner = _YF()
    yf = PointInTimeYFinance(inner, AS_OF, TODAY)

    assert await yf.get_info("AAPL") == {}
    history = await yf.get_history("AAPL", period="1y")
    days = history.index.tz_localize(None).normalize()
    assert days.max() <= pd.Timestamp(AS_OF)
    assert days.min() > pd.Timestamp(AS_OF) - pd.Timedelta(days=366)
    # Fetched wide enough to reach a year before as_of from today
    assert inner.asked[0] == ("history", "2y")

    await yf.get_closes("AAPL", date(2026, 5, 1), date(2026, 10, 27))
    assert inner.asked[-1] == ("closes", date(2026, 5, 1), date(2026, 6, 16))

    earnings = await yf.get_earnings_dates("AAPL")
    assert list(earnings["Reported EPS"]) == [1.6]  # the as_of day's after-close report wasn't out
    insider = await yf.get_insider_transactions("AAPL")
    assert [t["Transaction"] for t in insider] == ["Sale"]
    assert [n["title"] for n in await yf.get_news("AAPL")] == ["old"]


class _Fmp:
    async def get_company_profile(self, symbol: str) -> dict:
        return {"companyName": "Apple", "sector": "Technology", "marketCap": 4e12, "price": 260}

    async def _statements(self, limit: int) -> list[dict]:
        self.limit = limit
        return [
            {"date": "2026-03-28", "filingDate": "2026-07-31", "revenue": 3},
            {"date": "2025-09-27", "filingDate": "2025-10-31", "revenue": 2},
            {"date": "2024-09-28", "acceptedDate": "2024-11-01 06:01:00", "revenue": 1},
            {"date": "2023-09-30", "revenue": 0},  # no filing date: not provably known
        ]

    async def get_income_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        return await self._statements(limit)

    async def get_balance_sheets(self, symbol: str, limit: int = 5) -> list[dict]:
        return await self._statements(limit)

    async def get_cash_flow_statements(self, symbol: str, limit: int = 5) -> list[dict]:
        return await self._statements(limit)

    async def get_financial_ratios(self, symbol: str, limit: int = 5) -> list[dict]:
        return [{"date": "2026-03-28"}, {"date": "2025-12-27"}, {"date": "2025-09-27"}]

    async def get_key_metrics(self, symbol: str, limit: int = 5) -> list[dict]:
        return await self.get_financial_ratios(symbol, limit)

    async def get_earnings_surprises(self, symbol: str) -> list[dict]:
        return [{"date": "2026-07-30"}, {"date": "2026-06-15"}, {"date": "2026-04-30"}]

    async def get_earnings_call_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        return {"date": "2026-07-30" if quarter == 3 else "2026-04-30", "content": "..."}

    async def get_13f_institutional_ownership(self, symbol: str, limit: int = 4) -> list[dict]:
        return [{"date": "2026-06-30"}, {"date": "2026-03-31"}]


@pytest.mark.unit
async def test_fmp_keeps_filed_and_reported_periods_and_withholds_snapshots() -> None:
    fmp = PointInTimeFmp(_Fmp(), AS_OF)  # type: ignore[arg-type]

    profile = await fmp.get_company_profile("AAPL")
    assert profile == {"companyName": "Apple", "sector": "Technology"}
    assert not LIVE_PROFILE_FIELDS & profile.keys()

    income = await fmp.get_income_statements("AAPL", limit=1)
    assert [r["revenue"] for r in income] == [2]  # the March quarter was filed in July
    assert fmp._inner.limit == 4  # asked for a few more than needed
    await fmp.get_income_statements("AAPL", limit=5)
    assert fmp._inner.limit == 5  # but never above the free plan's cap (a 402: no data)
    assert [r["revenue"] for r in await fmp.get_balance_sheets("AAPL")] == [2, 1]
    assert len(await fmp.get_cash_flow_statements("AAPL")) == 2

    # No filing date: a period counts once 90 days have passed since it ended
    assert [r["date"] for r in await fmp.get_financial_ratios("AAPL")] == [
        "2025-12-27",
        "2025-09-27",
    ]
    assert len(await fmp.get_key_metrics("AAPL")) == 2
    assert [r["date"] for r in await fmp.get_earnings_surprises("AAPL")] == ["2026-04-30"]
    assert await fmp.get_earnings_call_transcript("AAPL", 2026, 3) == {}
    assert (await fmp.get_earnings_call_transcript("AAPL", 2026, 2))["date"] == "2026-04-30"
    assert [r["date"] for r in await fmp.get_13f_institutional_ownership("AAPL")] == ["2026-03-31"]

    assert await fmp.get_analyst_estimates("AAPL") == []
    assert await fmp.get_institutional_holders("AAPL") == []
    assert await fmp.get_info_fields("AAPL") == {}


@pytest.mark.unit
async def test_edgar_asks_for_the_10k_filed_by_as_of() -> None:
    inner = FakeEdgar()
    edgar = PointInTimeEdgar(inner, AS_OF)  # type: ignore[arg-type]
    assert "switching cost" in await edgar.get_business_section("AAPL")
    assert inner.filed_by == AS_OF
    assert "litigation" in await edgar.get_risk_factors("AAPL")


@pytest.mark.unit
def test_helpers() -> None:
    assert covering_period(date(2026, 10, 1), "1mo", TODAY) == "3mo"
    assert covering_period(date(2020, 1, 1), "1y", TODAY) == "10y"
    assert covering_period(date(2000, 1, 1), "1y", TODAY) == "max"
    rows = [{"d": "2026-06-15"}, {"d": "2026-06-16"}, {"d": "not a date"}, {"d": None}]
    assert known_by(rows, AS_OF, "d") == [{"d": "2026-06-15"}]
