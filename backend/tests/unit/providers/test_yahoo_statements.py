from datetime import date

import httpx
import pandas as pd
import pytest

from app.providers import yahoo_statements as statements
from app.providers.fmp import DailyCallBudget, FmpClient
from app.providers.yahoo_statements import (
    balance_rows,
    cash_flow_rows,
    earnings_rows,
    income_rows,
    ratio_rows,
)

NEW, OLD, EMPTY = pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")
NAN = float("nan")


def _income() -> pd.DataFrame:
    return pd.DataFrame(
        {
            OLD: {"Total Revenue": 80.0, "Net Income": -8.0, "Gross Profit": NAN},
            NEW: {"Total Revenue": 100.0, "Net Income": 10.0, "Gross Profit": 40.0},
            EMPTY: {"Total Revenue": NAN, "Net Income": NAN, "Gross Profit": NAN},
        }
    )


def _balance() -> pd.DataFrame:
    return pd.DataFrame(
        {
            NEW: {
                "Total Debt": 30.0,
                "Stockholders Equity": 60.0,
                "Current Assets": 50.0,
                "Current Liabilities": 25.0,
                "Total Assets": 200.0,
            },
            OLD: {"Total Debt": 30.0, "Stockholders Equity": -5.0, "Total Assets": 150.0},
        }
    )


@pytest.mark.unit
def test_income_rows_are_newest_first_without_inventing_missing_figures() -> None:
    rows = income_rows(_income())
    assert [r["date"] for r in rows] == ["2025-12-31", "2024-12-31"]  # the empty year is dropped
    assert rows[0] == {
        "date": "2025-12-31",
        "revenue": 100.0,
        "grossProfit": 40.0,
        "netIncome": 10.0,
    }
    assert "grossProfit" not in rows[1]  # not 0


@pytest.mark.unit
def test_balance_and_cash_flow_use_fmp_names_and_keep_capex_negative() -> None:
    assert balance_rows(_balance())[0]["totalStockholdersEquity"] == 60.0
    frame = pd.DataFrame(
        {NEW: {"Free Cash Flow": 5.0, "Capital Expenditure": -7.0, "Operating Cash Flow": 12.0}}
    )
    assert cash_flow_rows(frame) == [
        {
            "date": "2025-12-31",
            "operatingCashFlow": 12.0,
            "capitalExpenditure": -7.0,
            "freeCashFlow": 5.0,
        }
    ]
    assert income_rows(None) == [] and balance_rows(pd.DataFrame()) == []


@pytest.mark.unit
def test_ratios_are_fractions_and_negative_equity_gives_no_leverage_ratio() -> None:
    new, old = ratio_rows(_income(), _balance())
    assert new["netProfitMargin"] == pytest.approx(0.10)
    assert new["grossProfitMargin"] == pytest.approx(0.40)
    assert new["debtToEquityRatio"] == pytest.approx(0.5)
    assert new["returnOnEquity"] == pytest.approx(10 / 60)
    assert new["currentRatio"] == pytest.approx(2.0)
    assert old["netProfitMargin"] == pytest.approx(-0.10)
    assert "debtToEquityRatio" not in old and "returnOnEquity" not in old


@pytest.mark.unit
def test_earnings_rows_put_only_the_next_report_first_and_skip_old_unreported_ones() -> None:
    frame = pd.DataFrame(
        {"EPS Estimate": [0.5, 0.4, 0.3, 0.2], "Reported EPS": [NAN, NAN, 0.35, NAN]},
        index=pd.to_datetime(["2027-02-01", "2026-11-20", "2026-08-01", "2026-05-01"]),
    )
    assert earnings_rows(frame, date(2026, 11, 4)) == [
        {"date": "2026-11-20", "epsActual": None, "epsEstimated": 0.4},
        {"date": "2026-08-01", "epsActual": 0.35, "epsEstimated": 0.3},
    ]
    assert earnings_rows(None, date(2026, 11, 4)) == []


def _plan(allowed: str, seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params["symbol"]
        seen.append(symbol)
        if symbol != allowed:
            return httpx.Response(
                402,
                text="Premium Query Parameter: 'Special Endpoint : "
                "This value set for 'symbol' is not available under your current subscription",
            )
        return httpx.Response(200, json=[{"date": "2025-12-31", "revenue": 9.0}])

    return handler


@pytest.mark.unit
async def test_a_refused_symbol_doesnt_block_the_endpoint_for_other_symbols(make_http) -> None:
    seen: list[str] = []
    fmp = FmpClient(make_http(_plan("MSFT", seen)), api_key="k", budget=DailyCallBudget(limit=9))

    assert await fmp.get_income_statements("OSCR") == []
    assert await fmp.get_income_statements("OSCR", limit=3) == []
    assert (await fmp.get_income_statements("MSFT"))[0]["revenue"] == 9.0

    assert seen == ["OSCR", "MSFT"]  # the refused pair is remembered, the budget spared


@pytest.mark.unit
async def test_statements_fall_back_only_when_fmp_has_none(make_http) -> None:
    asked: list[tuple[str, str]] = []

    async def yahoo(endpoint: str, symbol: str) -> list[dict]:
        asked.append((endpoint, symbol))
        return [{"date": f"{2025 - i}-12-31", "revenue": 1.0} for i in range(6)]

    fmp = FmpClient(make_http(_plan("MSFT", [])), api_key="k", budget=DailyCallBudget(limit=9))
    fmp.use_statements(yahoo)

    assert (await fmp.get_income_statements("MSFT"))[0]["revenue"] == 9.0
    assert asked == []
    assert len(await fmp.get_income_statements("OSCR", limit=3)) == 3
    assert len(await fmp.get_earnings_surprises("OSCR")) == 5
    assert asked == [(statements.INCOME, "OSCR"), (statements.EARNINGS, "OSCR")]
