"""App-level tests: health endpoint, request logging middleware and the lifespan."""

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.main import app, lifespan
from app.middleware.request_logging import redact_query


@pytest.fixture
def client_with_state(session_factory):
    def _make(*, scheduler_running: bool = True, session_factory_override=None):
        app.state.container = SimpleNamespace(
            session_factory=session_factory_override or session_factory
        )
        app.state.scheduler = SimpleNamespace(running=scheduler_running)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return _make


@pytest.mark.integration
async def test_health_ok(client_with_state) -> None:
    async with client_with_state() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": "ok", "scheduler": "ok"}}


@pytest.mark.integration
async def test_health_degraded_when_db_down_or_scheduler_stopped(client_with_state) -> None:
    def broken():
        raise RuntimeError("db down")

    async with client_with_state(
        scheduler_running=False, session_factory_override=broken
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "unavailable", "scheduler": "stopped"}


@pytest.mark.integration
async def test_request_logging_levels_and_redaction(client_with_state, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.middleware.request_logging")
    async with client_with_state() as client:
        await client.get("/health?apikey=SECRET&x=1")
        await client.get("/missing")

    records = [r for r in caplog.records if r.name == "app.middleware.request_logging"]
    assert [r.levelno for r in records] == [logging.INFO, logging.WARNING]
    assert records[0].query == {"apikey": "***", "x": "1"}
    assert "SECRET" not in caplog.text


@pytest.mark.unit
def test_redact_query_is_case_insensitive() -> None:
    assert redact_query({"Authorization": "x", "symbol": "AAPL"}) == {
        "Authorization": "***",
        "symbol": "AAPL",
    }


@pytest.mark.integration
async def test_lifespan_starts_and_stops_scheduler() -> None:
    async with lifespan(app):
        assert app.state.scheduler.running
        assert app.state.container.registry.names()
    await asyncio.sleep(0)  # AsyncIOScheduler.shutdown runs on the next loop tick
    assert not app.state.scheduler.running
