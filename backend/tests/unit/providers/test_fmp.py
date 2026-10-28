import httpx
import pytest

from app.providers.errors import ProviderError, QuotaExceededError
from app.providers.fmp import DailyCallBudget, FmpClient


def _routes(table: dict[str, object]):
    """Answers /stable/<endpoint>?symbol=X from table["<endpoint> X"]."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "k"
        path = request.url.path.removeprefix("/stable/")
        return httpx.Response(200, json=table.get(f"{path} {request.url.params['symbol']}", []))

    return handler


@pytest.fixture
def fmp(make_http):
    table = {
        "profile AAPL": [{"companyName": "Apple"}],
        "income-statement AAPL": [{"revenue": 2}, {"revenue": 1}],
        "institutional-ownership/extract-analytics/holder AAPL": [
            {"holder": "small", "shares": 1},
            {"holder": "big", "shares": 9},
        ],
        "earning-call-transcript AAPL": [{"quarter": 1, "content": "x" * 20_000}],
        "ratios AAPL": {"unexpected": "shape"},
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
async def test_other_endpoints_hit_expected_stable_paths(make_http) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {k: v for k, v in request.url.params.items() if k != "apikey"}
        seen.append((request.url.path.removeprefix("/stable/"), params))
        return httpx.Response(200, json=[])

    client = FmpClient(make_http(handler), api_key="k", budget=DailyCallBudget(limit=100))
    await client.get_balance_sheets("aapl")
    await client.get_cash_flow_statements("AAPL")
    await client.get_key_metrics("AAPL")
    await client.get_earnings_surprises("AAPL")
    await client.get_analyst_estimates("AAPL")
    await client.get_13f_institutional_ownership("AAPL")
    assert [path for path, _ in seen] == [
        "balance-sheet-statement",
        "cash-flow-statement",
        "key-metrics",
        "earnings",
        "analyst-estimates",
        "institutional-ownership/symbol-positions-summary",
    ]
    assert seen[0][1] == {"symbol": "AAPL", "limit": "5", "period": "annual"}
    assert seen[3][1] == {"symbol": "AAPL", "limit": "5"}  # the free plan's maximum


@pytest.mark.unit
async def test_an_endpoint_outside_the_plan_is_no_data_not_a_failure(make_http, caplog) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if "earning-call-transcript" in request.url.path:
            return httpx.Response(402, text="Restricted Endpoint: not available under your plan")
        return httpx.Response(403, text="Legacy Endpoint")

    client = FmpClient(make_http(handler), api_key="k", budget=DailyCallBudget(limit=100))
    with caplog.at_level("WARNING"):
        assert await client.get_earnings_call_transcript("AAPL", 2026, 1) == {}
        assert await client.get_earnings_call_transcript("AAPL", 2025, 4) == {}
    assert caplog.text.count("not in your plan") == 1  # one warning per endpoint
    assert calls == 1  # and one call: the plan won't change mid-process, the budget is spared
    with pytest.raises(ProviderError, match="403"):  # anything else still fails the call
        await client.get_company_profile("AAPL")


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


class _SharedCounter:
    """The stored count, as another process (the worker) would see it too."""

    def __init__(self, start: int = 0, fail: bool = False) -> None:
        self.total = start
        self.fail = fail

    async def increment(self, day) -> int:
        if self.fail:
            raise RuntimeError("database down")
        self.total += 1
        return self.total


@pytest.mark.unit
async def test_a_restart_does_not_reset_the_stored_count() -> None:
    counter = _SharedCounter(start=248)  # spent before this process started
    budget = DailyCallBudget(limit=250, counter=counter)
    await budget.consume()
    await budget.consume()
    assert budget.used == 250
    with pytest.raises(QuotaExceededError):
        await budget.consume()


@pytest.mark.unit
async def test_another_process_spending_the_last_call_stops_this_one() -> None:
    counter = _SharedCounter()
    budget = DailyCallBudget(limit=3, counter=counter)
    await budget.consume()
    counter.total = 3  # the other process used the rest
    with pytest.raises(QuotaExceededError):
        await budget.consume()


@pytest.mark.unit
async def test_without_the_database_the_budget_still_counts_in_process(caplog) -> None:
    budget = DailyCallBudget(limit=2, counter=_SharedCounter(fail=True))
    await budget.consume()
    await budget.consume()
    with pytest.raises(QuotaExceededError):
        await budget.consume()
    assert "FMP call count not stored" in caplog.text


@pytest.mark.unit
def test_fmp_fields_take_yfinance_names_and_units() -> None:
    from app.providers.fmp import to_info_fields

    info = to_info_fields(
        profile={"companyName": "Apple Inc.", "sector": "Technology", "marketCap": 5.0e12},
        ratios=[{"debtToEquityRatio": 1.5241, "priceToEarningsRatio": 34.1, "currentRatio": 0.89}],
        metrics=[{"returnOnEquity": 1.52}],
        income=[
            {"revenue": 4.16e11, "netIncome": 1.12e11},
            {"revenue": 3.91e11, "netIncome": None},
        ],
        balance=[{"totalDebt": 1.12e11, "cashAndShortTermInvestments": 5.5e10}],
        cash_flow=[{"freeCashFlow": 9.88e10, "capitalExpenditure": -1.2e10}],
    )
    assert info["longName"] == "Apple Inc." and info["marketCap"] == 5.0e12
    assert info["debtToEquity"] == pytest.approx(152.41)  # yfinance reports percent
    assert info["trailingPE"] == 34.1 and info["returnOnEquity"] == 1.52
    assert info["revenueGrowth"] == pytest.approx(4.16 / 3.91 - 1)
    assert "earningsGrowth" not in info  # no previous year → missing, never 0
    assert info["totalCash"] == 5.5e10 and info["freeCashflow"] == 9.88e10
    assert info["quoteType"] == "EQUITY"
    assert to_info_fields({}, [], [], [], [], []) == {}
    assert to_info_fields({"isEtf": True}, [], [], [], [], [])["quoteType"] == "ETF"
    assert to_info_fields({"isFund": True}, [], [], [], [], [])["quoteType"] == "MUTUALFUND"


@pytest.mark.unit
async def test_info_fields_fetch_the_six_endpoints_once(make_http) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.removeprefix("/stable/"))
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json=[{"marketCap": 1.0e9}])
        return httpx.Response(200, json=[])

    client = FmpClient(make_http(handler), api_key="k", budget=DailyCallBudget(limit=100))
    assert await client.get_info_fields("AAPL") == {"marketCap": 1.0e9, "quoteType": "EQUITY"}
    assert sorted(seen) == sorted(
        [
            "profile",
            "ratios",
            "key-metrics",
            "income-statement",
            "balance-sheet-statement",
            "cash-flow-statement",
        ]
    )


@pytest.mark.unit
async def test_every_limit_shares_one_request_per_statement(make_http) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.url.params.get("limit")))
        n = int(request.url.params["limit"])
        return httpx.Response(200, json=[{"year": 2026 - i} for i in range(n)])

    budget = DailyCallBudget(limit=100)
    client = FmpClient(make_http(handler), api_key="k", budget=budget, earnings_limit=9)
    assert [r["year"] for r in await client.get_balance_sheets("AAPL", limit=1)] == [2026]
    assert len(await client.get_balance_sheets("AAPL", limit=3)) == 3
    assert len(await client.get_balance_sheets("AAPL", limit=5)) == 5
    assert seen == [("/stable/balance-sheet-statement", "5")]  # one call, then the cache
    assert budget.used == 1

    await client.get_earnings_surprises("AAPL")  # a paid plan's longer window
    assert seen[-1] == ("/stable/earnings", "9")
