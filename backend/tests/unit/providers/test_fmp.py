from datetime import date

import httpx
import pytest

from app.providers.errors import QuotaExceededError
from app.providers.fmp import DailyCallBudget, FmpClient, latest_13f_quarter


def _routes(table: dict[str, object], restricted: frozenset[str] = frozenset()):
    """Stable API: the endpoint is the path, the symbol a query parameter."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "k"
        path = request.url.path.removeprefix("/stable/")
        if path in restricted:
            return httpx.Response(402, text="Restricted Endpoint")
        key = f"{path}?{request.url.params.get('symbol')}"
        return httpx.Response(200, json=table.get(key, []))

    return handler


def _client(make_http, table: dict[str, object], **kwargs: object) -> FmpClient:
    return FmpClient(
        make_http(_routes(table, **kwargs)), api_key="k", budget=DailyCallBudget(limit=100)
    )


@pytest.fixture
def fmp(make_http):
    table = {
        "profile?AAPL": [{"companyName": "Apple", "marketCap": 4e12}],
        "income-statement?AAPL": [{"revenue": 2}, {"revenue": 1}],
        "institutional-ownership/extract-analytics/holder?AAPL": [
            {"investorName": "small", "sharesNumber": 1, "changeInSharesNumber": -1},
            {"investorName": "big", "sharesNumber": 9, "changeInSharesNumber": 3},
        ],
        "earning-call-transcript?AAPL": [{"period": "Q1", "content": "x" * 20_000}],
        "ratios?MSFT": {"unexpected": "shape"},
        "ratios?AAPL": [
            {"date": "2025-09-27", "grossProfitMargin": 0.47, "debtToEquityRatio": 1.52},
            {"date": "2024-09-28", "grossProfitMargin": 0.46, "debtToEquityRatio": 1.87},
        ],
        "key-metrics?AAPL": [
            {"date": "2025-09-27", "returnOnEquity": 1.5, "currentRatio": 0.89},
        ],
        "earnings?AAPL": [
            {"date": "2026-11-02", "epsActual": None, "epsEstimated": 1.99},
            {"date": "2026-07-30", "epsActual": 2.02, "epsEstimated": 1.89},
        ],
        "analyst-estimates?AAPL": [
            {"date": "2027-09-27", "revenueAvg": 5e11, "epsAvg": 9.1, "numAnalystsRevenue": 29}
        ],
    }
    return _client(make_http, table)


@pytest.mark.unit
async def test_profile_and_statements(fmp: FmpClient) -> None:
    profile = await fmp.get_company_profile("aapl")
    assert profile["companyName"] == "Apple"
    assert profile["mktCap"] == profile["marketCap"] == 4e12
    assert len(await fmp.get_income_statements("AAPL")) == 2
    assert await fmp.get_company_profile("MSFT") == {}


@pytest.mark.unit
async def test_unexpected_payload_becomes_empty_list(fmp: FmpClient) -> None:
    assert await fmp.get_financial_ratios("MSFT") == []


@pytest.mark.unit
async def test_ratios_and_key_metrics_are_merged_by_year(fmp: FmpClient) -> None:
    ratios = await fmp.get_financial_ratios("AAPL")
    assert ratios[0]["grossProfitMargin"] == 0.47
    assert ratios[0]["returnOnEquity"] == 1.5  # from key-metrics
    assert ratios[0]["debtToEquity"] == 1.52  # v3 name
    assert "returnOnEquity" not in ratios[1]  # no key-metrics row for that year
    assert await fmp.get_key_metrics("AAPL") == ratios


@pytest.mark.unit
async def test_earnings_skip_the_upcoming_report(fmp: FmpClient) -> None:
    surprises = await fmp.get_earnings_surprises("AAPL")
    assert len(surprises) == 1
    assert surprises[0]["actualEarningResult"] == 2.02
    assert surprises[0]["estimatedEarning"] == 1.89


@pytest.mark.unit
async def test_analyst_estimates_use_v3_names(fmp: FmpClient) -> None:
    [estimate] = await fmp.get_analyst_estimates("AAPL")
    assert estimate["estimatedRevenueAvg"] == 5e11
    assert estimate["estimatedEpsAvg"] == 9.1
    assert estimate["numberAnalystEstimatedRevenue"] == 29


@pytest.mark.unit
async def test_holders_sorted_by_shares(fmp: FmpClient) -> None:
    holders = await fmp.get_institutional_holders("AAPL")
    assert [h["holder"] for h in holders] == ["big", "small"]
    assert [h["change"] for h in holders] == [3, -1]
    trend = await fmp.get_13f_institutional_ownership("AAPL", limit=1)
    assert [t["investorName"] for t in trend] == ["big"]


@pytest.mark.unit
async def test_transcript_truncated_and_missing_is_empty(fmp: FmpClient) -> None:
    transcript = await fmp.get_earnings_call_transcript("AAPL", 2026, 1)
    assert len(transcript["content"]) == 15_000
    assert (transcript["year"], transcript["quarter"]) == (2026, 1)
    assert await fmp.get_earnings_call_transcript("MSFT", 2026, 1) == {}


@pytest.mark.unit
async def test_endpoints_outside_the_plan_are_empty(make_http) -> None:
    restricted = frozenset(
        {"earning-call-transcript", "institutional-ownership/extract-analytics/holder"}
    )
    client = _client(make_http, {}, restricted=restricted)
    assert await client.get_earnings_call_transcript("AAPL", 2026, 1) == {}
    assert await client.get_institutional_holders("AAPL") == []
    assert await client.get_13f_institutional_ownership("AAPL") == []


@pytest.mark.unit
async def test_endpoints_hit_expected_paths_and_params(make_http) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {k: v for k, v in request.url.params.items() if k != "apikey"}
        seen.append((request.url.path.removeprefix("/stable/"), params))
        return httpx.Response(200, json=[])

    client = FmpClient(make_http(handler), api_key="k", budget=DailyCallBudget(limit=100))
    await client.get_balance_sheets("AAPL", limit=3)
    await client.get_cash_flow_statements("AAPL")
    await client.get_earnings_surprises("AAPL")
    await client.get_analyst_estimates("AAPL")
    await client.get_earnings_call_transcript("AAPL", 2025, 4)
    annual = {"symbol": "AAPL", "period": "annual"}
    assert seen == [
        ("balance-sheet-statement", {**annual, "limit": "3"}),
        ("cash-flow-statement", {**annual, "limit": "5"}),
        ("earnings", {"symbol": "AAPL", "limit": "5"}),
        ("analyst-estimates", {**annual, "limit": "8"}),
        ("earning-call-transcript", {"symbol": "AAPL", "year": "2025", "quarter": "4"}),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 27), (2026, 2)),  # Q3 13Fs are not due until mid-November
        (date(2026, 11, 20), (2026, 3)),
        (date(2026, 2, 1), (2025, 3)),
        (date(2026, 2, 20), (2025, 4)),
    ],
)
def test_latest_13f_quarter(today: date, expected: tuple[int, int]) -> None:
    assert latest_13f_quarter(today) == expected


@pytest.mark.unit
async def test_budget_counts_only_uncached_calls_and_stops_at_limit(make_http) -> None:
    budget = DailyCallBudget(limit=2)
    client = FmpClient(make_http(_routes({})), api_key="k", budget=budget)

    await client.get_company_profile("AAPL")
    await client.get_company_profile("AAPL")  # cached — free
    assert budget.used == 1
    await client.get_company_profile("MSFT")
    with pytest.raises(QuotaExceededError):
        await client.get_company_profile("NVDA")
