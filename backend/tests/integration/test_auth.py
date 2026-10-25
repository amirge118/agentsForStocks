"""API-key authentication on /api/v1 (health stays public)."""

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from pydantic import ValidationError

from app.container import build_container
from app.core.config import Settings
from app.main import app

KEY_A = "a" * 32
KEY_B = "b" * 40


@pytest.fixture
async def client_for(session_factory) -> AsyncIterator[Callable[[Settings], httpx.AsyncClient]]:
    containers = []

    def _make(settings: Settings) -> httpx.AsyncClient:
        container = build_container(settings, session_factory)
        containers.append(container)
        app.state.container = container
        app.state.scheduler = type("S", (), {"running": True})()
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    yield _make
    for container in containers:
        await container.aclose()


def _secured() -> Settings:
    return Settings(openviking_enabled=False, watchlist="AAPL", api_keys=f"{KEY_A}, {KEY_B}")


@pytest.mark.integration
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong" * 8}, {"X-API-Key": ""}])
async def test_requests_without_a_valid_key_are_rejected(client_for, headers) -> None:
    async with client_for(_secured()) as client:
        for method, path in [
            ("GET", "/api/v1/agents"),
            ("GET", "/api/v1/symbols"),
            ("GET", "/api/v1/runs"),
            ("POST", "/api/v1/pipeline/runs"),
        ]:
            resp = await client.request(method, path, headers=headers, json={})
            assert resp.status_code == 401, path
            assert resp.json() == {"detail": "Missing or invalid API key"}
            assert resp.headers["www-authenticate"] == "X-API-Key"


@pytest.mark.integration
@pytest.mark.parametrize("key", [KEY_A, KEY_B])
async def test_any_configured_key_is_accepted(client_for, key) -> None:
    async with client_for(_secured()) as client:
        resp = await client.get("/api/v1/symbols", headers={"X-API-Key": key})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_health_is_public(client_for) -> None:
    async with client_for(_secured()) as client:
        assert (await client.get("/health")).status_code == 200


@pytest.mark.integration
async def test_auth_disabled_in_development_without_keys(client_for) -> None:
    async with client_for(Settings(openviking_enabled=False, watchlist="AAPL")) as client:
        assert (await client.get("/api/v1/agents")).status_code == 200


@pytest.mark.integration
async def test_second_manual_run_while_one_is_active_returns_409(client_for) -> None:
    async with client_for(_secured()) as client:
        headers = {"X-API-Key": KEY_A}
        first = await client.post(
            "/api/v1/pipeline/runs", headers=headers, json={"agents": ["technicals"]}
        )
        second = await client.post(
            "/api/v1/pipeline/runs", headers=headers, json={"agents": ["technicals"]}
        )
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == "A pipeline run is already in progress"


@pytest.mark.unit
def test_production_refuses_to_start_without_keys() -> None:
    with pytest.raises(ValidationError, match="API_KEYS must be set"):
        Settings(environment="production", api_keys="")
    assert Settings(environment="production", api_keys=KEY_A).auth_enabled


@pytest.mark.unit
def test_short_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(api_keys="short")


@pytest.mark.unit
def test_openapi_documents_the_api_key_scheme() -> None:
    schemes = app.openapi()["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key from the API_KEYS setting",
    }
