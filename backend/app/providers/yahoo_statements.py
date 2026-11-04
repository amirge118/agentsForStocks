"""
Yahoo's annual statements and earnings dates, shaped like FMP's rows — for symbols
FMP's plan doesn't cover, so agents read one vocabulary whichever source answered.

A figure Yahoo doesn't report is left out, never set to 0. Rows carry no filing date,
so point-in-time runs (app/providers/point_in_time.py) leave them out.
"""

import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

INCOME = "income-statement"
BALANCE = "balance-sheet-statement"
CASH_FLOW = "cash-flow-statement"
RATIOS = "ratios"
EARNINGS = "earnings"

_INCOME_ROWS = {
    "revenue": "Total Revenue",
    "grossProfit": "Gross Profit",
    "operatingIncome": "Operating Income",
    "netIncome": "Net Income",
    "ebitda": "EBITDA",
    "weightedAverageShsOutDil": "Diluted Average Shares",
}
_BALANCE_ROWS = {
    "totalDebt": "Total Debt",
    "cashAndCashEquivalents": "Cash And Cash Equivalents",
    "cashAndShortTermInvestments": "Cash Cash Equivalents And Short Term Investments",
    "totalStockholdersEquity": "Stockholders Equity",
    "totalAssets": "Total Assets",
    "goodwillAndIntangibleAssets": "Goodwill And Other Intangible Assets",
    "totalCurrentAssets": "Current Assets",
    "totalCurrentLiabilities": "Current Liabilities",
}
_CASH_FLOW_ROWS = {
    "operatingCashFlow": "Operating Cash Flow",
    "capitalExpenditure": "Capital Expenditure",
    "freeCashFlow": "Free Cash Flow",
    "depreciationAndAmortization": "Depreciation And Amortization",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return None if math.isnan(value) or math.isinf(value) else float(value)


def _rows(frame: pd.DataFrame | None, names: Mapping[str, str]) -> list[dict[str, Any]]:
    """One dict per period, most recent first. A period with no figure at all is left out."""
    if frame is None or frame.empty:
        return []
    rows = []
    for period in sorted(frame.columns, reverse=True):
        figures = {
            field: number
            for field, label in names.items()
            if label in frame.index and (number := _number(frame.at[label, period])) is not None
        }
        if figures:
            rows.append({"date": pd.Timestamp(period).date().isoformat(), **figures})
    return rows


def income_rows(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    return _rows(frame, _INCOME_ROWS)


def balance_rows(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    return _rows(frame, _BALANCE_ROWS)


def cash_flow_rows(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    return _rows(frame, _CASH_FLOW_ROWS)


def _ratio(top: float | None, bottom: float | None) -> float | None:
    return top / bottom if top is not None and bottom else None


def ratio_rows(income: pd.DataFrame | None, balance: pd.DataFrame | None) -> list[dict[str, Any]]:
    """The margins and balance-sheet ratios FMP's `ratios` gives, as fractions, per period."""
    by_day = {row["date"]: row for row in balance_rows(balance)}
    rows = []
    for inc in income_rows(income):
        bal = by_day.get(inc["date"], {})
        revenue, equity = inc.get("revenue"), bal.get("totalStockholdersEquity")
        # A company with negative equity has no meaningful D/E or ROE
        book = equity if equity is not None and equity > 0 else None
        figures = {
            "grossProfitMargin": _ratio(inc.get("grossProfit"), revenue),
            "operatingProfitMargin": _ratio(inc.get("operatingIncome"), revenue),
            "netProfitMargin": _ratio(inc.get("netIncome"), revenue),
            "returnOnEquity": _ratio(inc.get("netIncome"), book),
            "debtToEquityRatio": _ratio(bal.get("totalDebt"), book),
            "currentRatio": _ratio(
                bal.get("totalCurrentAssets"), bal.get("totalCurrentLiabilities")
            ),
        }
        present = {field: value for field, value in figures.items() if value is not None}
        if present:
            rows.append({"date": inc["date"], **present})
    return rows


def earnings_rows(frame: pd.DataFrame | None, today: date) -> list[dict[str, Any]]:
    """Like FMP's `earnings`: most recent first, the next report first with epsActual = None."""
    if frame is None or frame.empty:
        return []
    upcoming: list[dict[str, Any]] = []
    reported: list[dict[str, Any]] = []
    for moment, row in frame.sort_index(ascending=False).iterrows():
        day = pd.Timestamp(moment).date()
        actual = _number(row.get("Reported EPS"))
        entry = {
            "date": day.isoformat(),
            "epsActual": actual,
            "epsEstimated": _number(row.get("EPS Estimate")),
        }
        if actual is not None:
            reported.append(entry)
        elif day >= today:
            upcoming.append(entry)
    return upcoming[-1:] + reported
