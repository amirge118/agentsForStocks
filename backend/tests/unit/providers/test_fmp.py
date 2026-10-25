import httpx
import pytest

from app.providers.errors import QuotaExceededError
from app.providers.fmp import DailyCallBudget, FmpClient


def _routes(table: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "k"
        path = request.url.path.removeprefix("/api/v3/")
        return httpx.Response(200, json=table.get(path, []))

    return handler


@pytest.fixture
def fmp(make_http):
    table = {
        "profile/AAPL": [{"companyName": "Apple"}],
        "income-statement/AAPL": [{"revenue": 2}, {"revenue": 1}],
        "institutional-holder/AAPL": [
            {"holder": "small", "shares": 1},
            {"holder": "big", "shares": 9},
        ],
        "earning_call_transcript/AAPL": [{"quarter": 1, "content": "x" * 20_000}],
        "ratios/AAPL": {"unexpected": "shape"},
    }
    return FmpClient(make_http(_routes(table)), api_key="k", budget=DailyCallBudget(limit=100))


@pytest.mark.unit
async def test_profile_and_statements(fmp: FmpClient) -> None:
    assert (await fmp.get_company_profile("aapl"))["companyName"] == "Apple"
    assert len(await fmp.get_income_statements("AAPL")) == 2
    assert await fmp.get_company_profile("MSFT") == {}


@pytest.mark.unit
async def test_unexpected_payload_becomes_empty_list(fmp: FmpClient) -> None:
    assert await fmp.get_financial_ratios("AAPL") == []


@pytest.mark.unit
async def test_holders_sorted_by_shares(fmp: FmpClient) -> None:
    holders = await fmp.get_institutional_holders("AAPL")
    assert [h["holder"] for h in holders] == ["big", "small"]


@pytest.mark.unit
async def test_transcript_truncated_and_missing_is_empty(fmp: FmpClient) -> None:
    transcript = await fmp.get_earnings_call_transcript("AAPL", 2026, 1)
    assert len(transcript["content"]) == 15_000
    assert await fmp.get_earnings_call_transcript("MSFT", 2026, 1) == {}


@pytest.mark.unit
async def test_other_endpoints_hit_expected_paths(make_http) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.removeprefix("/api/v3/"))
        return httpx.Response(200, json=[])

    client = FmpClient(make_http(handler), api_key="k", budget=DailyCallBudget(limit=100))
    await client.get_balance_sheets("AAPL")
    await client.get_cash_flow_statements("AAPL")
    await client.get_key_metrics("AAPL")
    await client.get_earnings_surprises("AAPL")
    await client.get_analyst_estimates("AAPL")
    await client.get_13f_institutional_ownership("AAPL")
    assert seen == [
        "balance-sheet-statement/AAPL",
        "cash-flow-statement/AAPL",
        "key-metrics/AAPL",
        "earnings-surprises/AAPL",
        "analyst-estimates/AAPL",
        "institutional-ownership/symbol-ownership",
    ]


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
