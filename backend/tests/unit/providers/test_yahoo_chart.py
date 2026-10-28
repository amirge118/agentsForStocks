from datetime import date

import httpx
import pytest

from app.providers.yahoo_chart import YahooChartClient

# The shape Yahoo returned live for AAPL (range=5d), trimmed to three sessions
CHART = {
    "chart": {
        "result": [
            {
                "meta": {
                    "currency": "USD",
                    "symbol": "AAPL",
                    "instrumentType": "EQUITY",
                    "exchangeTimezoneName": "America/New_York",
                    "regularMarketPrice": 345.57,
                    "chartPreviousClose": 342.94,
                    "longName": "Apple Inc.",
                    "fiftyTwoWeekHigh": 351.73,
                    "fiftyTwoWeekLow": 243.42,
                    "regularMarketVolume": 11792629,
                },
                "timestamp": [1792503000, 1792589400, 1792675800],
                "indicators": {
                    "quote": [
                        {
                            "open": [339.86, 339.36, 344.94],
                            "high": [343.06, 345.25, 348.36],
                            "low": [338.70, 338.83, 342.28],
                            "close": [339.5, 343.99, None],  # a session not closed yet
                            "volume": [35851400, 35614100, 46898900],
                        }
                    ],
                    # Split- and dividend-adjusted (yfinance's auto_adjust)
                    "adjclose": [{"adjclose": [338.9, 343.4, None]}],
                },
            }
        ],
        "error": None,
    }
}
NOT_FOUND = {"chart": {"result": None, "error": {"code": "Not Found", "description": "delisted"}}}


def _client(make_http, seen: list[httpx.Request] | None = None) -> YahooChartClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/AAPL"):
            return httpx.Response(200, json=CHART)
        return httpx.Response(404, json=NOT_FOUND)

    return YahooChartClient(make_http(handler))


@pytest.mark.unit
async def test_history_is_shaped_like_yfinance(make_http) -> None:
    seen: list[httpx.Request] = []
    df = await _client(make_http, seen).get_history("aapl", period="3mo")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert list(df["Close"]) == [339.5, 343.99]  # the unclosed session is dropped
    assert str(df.index.tz) == "America/New_York"
    request = seen[0]
    assert request.url.params["range"] == "3mo" and request.url.params["interval"] == "1d"
    assert "Mozilla" in request.headers["User-Agent"]


@pytest.mark.unit
async def test_quote_uses_yfinance_info_names(make_http) -> None:
    quote = await _client(make_http).get_quote("AAPL")
    assert quote["regularMarketPrice"] == quote["currentPrice"] == 345.57
    assert quote["previousClose"] == 342.94 and quote["longName"] == "Apple Inc."
    assert quote["_source"] == "yahoo_chart" and quote["quoteType"] == "EQUITY"


@pytest.mark.unit
async def test_unknown_symbol_is_empty_not_an_error(make_http) -> None:
    client = _client(make_http)
    assert (await client.get_history("NOPE")).empty
    assert await client.get_quote("NOPE") == {}


@pytest.mark.unit
async def test_adjusted_closes_for_a_date_range(make_http) -> None:
    seen: list[httpx.Request] = []
    client = _client(make_http, seen)
    # The sessions are 2026-10-20 … 2026-10-22; the third has not closed
    closes = await client.get_adjusted_closes("aapl", date(2026, 10, 20), date(2026, 10, 23))
    assert list(closes) == [338.9, 343.4]  # adjclose, not close
    assert [d.date() for d in closes.index] == [date(2026, 10, 20), date(2026, 10, 21)]
    params = seen[0].url.params
    assert (params["period1"], params["period2"]) == ("1792454400", "1792713600")
    assert params["interval"] == "1d" and params["includeAdjustedClose"] == "true"
    # [start, end): a range that stops before the second session keeps only the first
    narrow = await client.get_adjusted_closes("AAPL", date(2026, 10, 20), date(2026, 10, 21))
    assert list(narrow) == [338.9]


@pytest.mark.unit
async def test_no_adjusted_closes_is_empty_never_unadjusted(make_http, caplog) -> None:
    import copy

    import httpx as _httpx

    unadjusted = copy.deepcopy(CHART)
    del unadjusted["chart"]["result"][0]["indicators"]["adjclose"]

    def handler(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(200, json=unadjusted)

    client = YahooChartClient(make_http(handler))
    assert (await client.get_adjusted_closes("AAPL", date(2026, 10, 1), date(2026, 11, 1))).empty
    assert "no adjusted closes" in caplog.text
    unknown = _client(make_http)
    assert (await unknown.get_adjusted_closes("NOPE", date(2026, 10, 1), date(2026, 11, 1))).empty


@pytest.mark.unit
async def test_symbol_exists_tells_unknown_from_unreachable(make_http) -> None:
    client = _client(make_http)
    assert await client.symbol_exists("AAPL") is True
    assert await client.symbol_exists("NOPE") is False  # Yahoo's 404: no such ticker
    down = YahooChartClient(make_http(lambda request: httpx.Response(503)))
    assert await down.symbol_exists("AAPL") is None  # can't tell: don't block the user
