import pandas as pd
import pytest

from app.providers.cache import TTLCache
from app.providers.errors import ProviderError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy
from app.providers.yfinance import YFinanceClient


class _FakeTicker:
    calls = 0
    history_args: dict = {}

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self) -> dict:
        _FakeTicker.calls += 1
        return {"symbol": self.symbol, "regularMarketPrice": 10.0}

    def history(self, **kwargs: str | bool) -> pd.DataFrame:
        _FakeTicker.history_args = kwargs
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


@pytest.mark.unit
async def test_closes_are_adjusted_and_end_exclusive() -> None:
    from datetime import date

    closes = await _client().get_closes("aapl", date(2026, 10, 1), date(2026, 10, 20))
    assert list(closes) == [1.0, 2.0]
    assert _FakeTicker.history_args == {
        "start": "2026-10-01",
        "end": "2026-10-20",
        "interval": "1d",
        "auto_adjust": True,
    }


@pytest.mark.unit
async def test_closes_empty_when_yahoo_has_none() -> None:
    from datetime import date

    class NoData(_FakeTicker):
        def history(self, **kwargs: str | bool) -> pd.DataFrame:
            return pd.DataFrame()

    assert (await _client(NoData).get_closes("AAPL", date(2026, 1, 1), date(2026, 2, 1))).empty
