import pandas as pd
import pytest

from app.providers.cache import TTLCache
from app.providers.errors import ProviderError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy
from app.providers.yfinance import YFinanceClient


class _FakeTicker:
    calls = 0

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self) -> dict:
        _FakeTicker.calls += 1
        return {"symbol": self.symbol, "regularMarketPrice": 10.0}

    def history(self, period: str, interval: str) -> pd.DataFrame:
        return pd.DataFrame({"Close": [1.0, 2.0]})

    @property
    def earnings_dates(self) -> None:
        return None

    def get_insider_transactions(self) -> pd.DataFrame:
        return pd.DataFrame([{"Transaction": "Buy"}])

    def get_news(self, count: int = 10) -> list[dict]:
        # Like yfinance 1.x: `count` articles are requested, Yahoo may send a few more
        return [{"title": f"h{i}"} for i in range(count + 5)]


def _client(factory=_FakeTicker) -> YFinanceClient:
    return YFinanceClient(
        rate_limiter=RateLimiter({}, default_rps=1000),
        cache=TTLCache(60),
        retry_policy=RetryPolicy(max_attempts=2, timeout_seconds=1.0, base_backoff_seconds=0.0),
        ticker_factory=factory,
    )


@pytest.mark.unit
async def test_methods_return_normalised_data() -> None:
    yf = _client()
    assert (await yf.get_info("aapl"))["symbol"] == "AAPL"
    assert list((await yf.get_history("AAPL"))["Close"]) == [1.0, 2.0]
    assert (await yf.get_earnings_dates("AAPL")).empty
    assert await yf.get_insider_transactions("AAPL") == [{"Transaction": "Buy"}]
    assert len(await yf.get_news("AAPL", count=20)) == 20


@pytest.mark.unit
async def test_info_is_cached() -> None:
    _FakeTicker.calls = 0
    yf = _client()
    await yf.get_info("AAPL")
    await yf.get_info("AAPL")
    assert _FakeTicker.calls == 1


@pytest.mark.unit
async def test_library_errors_are_retried_then_raised() -> None:
    class Broken:
        def __init__(self, symbol: str) -> None:
            pass

        @property
        def info(self) -> dict:
            raise ConnectionError("yahoo down")

    with pytest.raises(ProviderError):
        await _client(Broken).get_info("AAPL")


class _CrumbBlocked(_FakeTicker):
    """What yfinance does when Yahoo refuses its crumb: no price, errors elsewhere."""

    @property
    def info(self) -> dict:
        return {"symbol": self.symbol, "sector": "Technology"}  # no price

    def history(self, period: str, interval: str) -> pd.DataFrame:
        raise RuntimeError("401 Invalid Crumb")

    def get_insider_transactions(self) -> pd.DataFrame:
        raise RuntimeError("401 Invalid Crumb")

    def get_news(self, count: int = 10) -> list[dict]:
        raise RuntimeError("401 Invalid Crumb")


class _Chart:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_quote(self, symbol: str) -> dict:
        self.calls.append(f"quote {symbol}")
        return {"regularMarketPrice": 345.0, "currentPrice": 345.0, "_source": "yahoo_chart"}

    async def get_history(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        self.calls.append(f"history {symbol} {period}")
        return pd.DataFrame({"Close": [344.0, 345.0]})


def _with_fallback(factory, chart: _Chart) -> YFinanceClient:
    return YFinanceClient(
        rate_limiter=RateLimiter({}, default_rps=1000),
        cache=TTLCache(60),
        retry_policy=RetryPolicy(max_attempts=2, timeout_seconds=1.0, base_backoff_seconds=0.0),
        ticker_factory=factory,
        fallback=chart,
    )


@pytest.mark.unit
async def test_the_chart_fills_in_when_yfinance_has_no_prices() -> None:
    chart = _Chart()
    yf = _with_fallback(_CrumbBlocked, chart)
    info = await yf.get_info("AAPL")
    # yfinance's own fields are kept; the chart adds the price
    assert (info["sector"], info["regularMarketPrice"], info["_source"]) == (
        "Technology",
        345.0,
        "yahoo_chart",
    )
    assert list((await yf.get_history("AAPL", period="1y"))["Close"]) == [344.0, 345.0]
    # Data the chart can't give degrades to empty instead of failing the agent
    assert await yf.get_insider_transactions("AAPL") == []
    assert await yf.get_news("AAPL") == []
    assert chart.calls == ["quote AAPL", "history AAPL 1y"]


@pytest.mark.unit
async def test_the_chart_is_not_asked_when_yfinance_works() -> None:
    chart = _Chart()
    yf = _with_fallback(_FakeTicker, chart)
    assert (await yf.get_info("AAPL"))["regularMarketPrice"] == 10.0
    assert list((await yf.get_history("AAPL"))["Close"]) == [1.0, 2.0]
    assert chart.calls == []


@pytest.mark.unit
async def test_without_a_fallback_failures_still_raise() -> None:
    with pytest.raises(ProviderError):
        await _client(_CrumbBlocked).get_insider_transactions("AAPL")


@pytest.mark.unit
async def test_fundamentals_fill_a_quote_only_info_and_yfinance_wins() -> None:
    asked: list[str] = []

    async def fundamentals(symbol: str) -> dict:
        asked.append(symbol)
        return {"marketCap": 5.0e12, "trailingPE": 34.0, "sector": "Tech (FMP)"}

    yf = YFinanceClient(
        rate_limiter=RateLimiter({}, default_rps=1000),
        cache=TTLCache(60),
        retry_policy=RetryPolicy(max_attempts=2, timeout_seconds=1.0, base_backoff_seconds=0.0),
        ticker_factory=_CrumbBlocked,
        fallback=_Chart(),
        fundamentals=fundamentals,
    )
    info = await yf.get_info("AAPL")
    assert (info["marketCap"], info["trailingPE"], info["regularMarketPrice"]) == (
        5.0e12,
        34.0,
        345.0,
    )
    assert info["sector"] == "Technology"  # yfinance's own value wins over FMP's
    assert asked == ["AAPL"]


@pytest.mark.unit
async def test_fundamentals_are_not_fetched_when_yfinance_has_a_market_cap() -> None:
    class _Full(_FakeTicker):
        @property
        def info(self) -> dict:
            return {"symbol": self.symbol, "regularMarketPrice": 10.0, "marketCap": 1.0e9}

    async def fundamentals(symbol: str) -> dict:
        raise AssertionError("FMP should not be called")

    yf = YFinanceClient(
        rate_limiter=RateLimiter({}, default_rps=1000),
        cache=TTLCache(60),
        ticker_factory=_Full,
        fundamentals=fundamentals,
    )
    assert (await yf.get_info("AAPL"))["marketCap"] == 1.0e9


@pytest.mark.unit
async def test_a_failing_fundamentals_source_leaves_the_quote() -> None:
    async def fundamentals(symbol: str) -> dict:
        raise ProviderError("FMP daily budget of 250 calls exhausted")

    yf = YFinanceClient(
        rate_limiter=RateLimiter({}, default_rps=1000),
        cache=TTLCache(60),
        retry_policy=RetryPolicy(max_attempts=2, timeout_seconds=1.0, base_backoff_seconds=0.0),
        ticker_factory=_CrumbBlocked,
        fallback=_Chart(),
        fundamentals=fundamentals,
    )
    info = await yf.get_info("AAPL")
    assert info["regularMarketPrice"] == 345.0 and "marketCap" not in info
