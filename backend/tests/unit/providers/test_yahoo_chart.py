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
                    ]
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
