"""
Company archetypes for golden-scenario tests: the same agents, fed data that
should push them in a known direction. The LLM stays fake — these scenarios
check the deterministic part of every agent (metrics, fallback signals, data
gaps, contract rules) and what the prompt tells Claude.
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tests.factories import INFO, FakeEdgar, FakeFmp, FakeYFinance, price_history


@dataclass(frozen=True)
class Scenario:
    name: str
    yfinance: FakeYFinance
    fmp: FakeFmp
    edgar: FakeEdgar


class EmptyYFinance(FakeYFinance):
    def __init__(self) -> None:
        super().__init__(info={}, history=pd.DataFrame())

    async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_insider_transactions(self, symbol: str) -> list[dict]:
        return []

    async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
        return []


def _empty_edgar() -> FakeEdgar:
    edgar = FakeEdgar()
    edgar.business = ""
    edgar.risk = ""
    return edgar


def _empty_fmp() -> FakeFmp:
    empty: dict[str, Any] = {key: [] for key in FakeFmp().data}
    empty.update(profile={}, transcripts={})
    return FakeFmp(**empty)


def _trend(days: int, drift: float) -> pd.DataFrame:
    return price_history(days=days, drift=drift)


def baseline() -> Scenario:
    """The default fakes: a large, profitable, steadily growing company."""
    return Scenario("baseline", FakeYFinance(), FakeFmp(), FakeEdgar())


def no_data() -> Scenario:
    """Every provider returns nothing (blocked network, unknown ticker)."""
    return Scenario("no_data", EmptyYFinance(), _empty_fmp(), _empty_edgar())


def overvalued() -> Scenario:
    """A huge market cap on small cash flows: intrinsic value far below the price."""
    info = {
        **INFO,
        "marketCap": 3.0e13,
        "freeCashflow": 2.0e9,
        "ebitda": 3.0e9,
        "netIncomeToCommon": 1.5e9,
        "trailingPE": 400.0,
        "forwardPE": 300.0,
    }
    fmp = FakeFmp()
    for row in fmp.data["cash_flow"]:
        row["freeCashFlow"] = 2.0e9
    return Scenario("overvalued", FakeYFinance(info=info), fmp, FakeEdgar())


def downtrend() -> Scenario:
    """A year of steadily falling prices."""
    history = _trend(250, drift=-0.004)
    return Scenario("downtrend", FakeYFinance(history=history), FakeFmp(), FakeEdgar())


def uptrend() -> Scenario:
    """A year of strongly rising prices."""
    history = _trend(250, drift=0.006)
    return Scenario("uptrend", FakeYFinance(history=history), FakeFmp(), FakeEdgar())


def distressed() -> Scenario:
    """Shrinking revenue, losses, heavy debt and thin liquidity."""
    info = {
        **INFO,
        "returnOnEquity": -0.15,
        "profitMargins": -0.08,
        "operatingMargins": -0.05,
        "revenueGrowth": -0.12,
        "earningsGrowth": -0.4,
        "currentRatio": 0.6,
        "debtToEquity": 450.0,
        "freeCashflow": -2.0e9,
        "beta": 2.1,
    }
    fmp = FakeFmp()
    years = len(fmp.data["income"])
    for i, row in enumerate(fmp.data["income"]):  # most recent first, revenue shrinking
        row["revenue"] = 1e10 * (1 - 0.1) ** (years - 1 - i) * 0.7
        row["netIncome"] = -5e8
    for row in fmp.data["cash_flow"]:
        row["freeCashFlow"] = -1e9
    for row in fmp.data["ratios"]:
        row.update(debtToEquityRatio=4.5, currentRatio=0.6)
    edgar = FakeEdgar(risk="We face going concern doubt, covenant breaches and litigation.")
    return Scenario("distressed", FakeYFinance(info=info, history=_trend(250, -0.003)), fmp, edgar)


ALL = (baseline, no_data, overvalued, downtrend, uptrend, distressed)
