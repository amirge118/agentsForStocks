import httpx
import pytest

from app.providers.errors import ProviderError


@pytest.mark.unit
async def test_get_json_retries_5xx_then_succeeds(make_http) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503) if attempts == 1 else httpx.Response(200, json={"ok": True})

    http = make_http(handler)
    assert await http.get_json("https://api.example/x") == {"ok": True}
    assert attempts == 2


@pytest.mark.unit
async def test_client_errors_are_not_retried(make_http) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    http = make_http(handler)
    with pytest.raises(ProviderError, match="401"):
        await http.get_json("https://api.example/x")
    assert attempts == 1


@pytest.mark.unit
async def test_connection_errors_are_retried(make_http) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http = make_http(handler)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        await http.get_text("https://api.example/x")


@pytest.mark.unit
async def test_responses_are_cached_and_on_request_runs_per_network_call(make_http) -> None:
    hits = 0
    counted = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(200, json=[request.url.params["q"]])

    def count() -> None:
        nonlocal counted
        counted += 1

    http = make_http(handler)
    for _ in range(3):
        assert await http.get_json(
            "https://api.example/s", params={"q": "a"}, on_request=count
        ) == ["a"]
    await http.get_json("https://api.example/s", params={"q": "b"}, on_request=count)
    assert hits == 2
    assert counted == 2
