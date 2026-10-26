"""
Checks that only a real PostgreSQL can answer: the Alembic migrations, the
postgresql ON CONFLICT upsert and the per-symbol "latest" query. SQLite covers
everything else. Runs when TEST_POSTGRES_URL is set (CI provides a service):

    TEST_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agents_test pytest
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.repositories.agent_results import AgentResultRepository
from app.repositories.llm_calls import LLMCallRepository

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL not set"),
]

D1, D2 = date(2026, 10, 22), date(2026, 10, 23)


def _alembic(direction: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", POSTGRES_URL)
    backend_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    if direction == "upgrade":
        command.upgrade(cfg, "head")
    else:
        command.downgrade(cfg, "base")


@pytest.fixture
async def pg_session_factory(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # env.py runs its own event loop, so run migrations in a worker thread
    await asyncio.to_thread(_alembic, "upgrade", monkeypatch)
    engine = create_async_engine(POSTGRES_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
    await asyncio.to_thread(_alembic, "downgrade", monkeypatch)


async def test_migrations_create_the_expected_schema(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        conn = await session.connection()
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert {"agent_results", "agent_runs", "llm_calls", "alembic_version"} <= set(tables)
        version = (await session.execute(text("select version_num from alembic_version"))).scalar()
        assert version == "0004"
        columns = await conn.run_sync(lambda c: inspect(c).get_columns("llm_calls"))
        assert "provider" in {col["name"] for col in columns}


async def test_upsert_on_postgres_is_idempotent(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        repo = AgentResultRepository(session)
        for run_id, value in (("r1", 1), ("r2", 2)):
            await repo.upsert(
                agent_type="moat", symbol="AAPL", run_date=D1, run_id=run_id, result={"v": value}
            )
        await session.commit()
        assert await repo.get_for_date("AAPL", D1) == {"moat": {"v": 2}}
        count = (await session.execute(text("select count(*) from agent_results"))).scalar()
        assert count == 1


async def test_latest_per_symbol_on_postgres(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        repo = AgentResultRepository(session)
        for symbol, day, run_id in (("AAPL", D1, "a1"), ("AAPL", D2, "a2"), ("MSFT", D1, "m1")):
            await repo.upsert(
                agent_type="recommendation", symbol=symbol, run_date=day, run_id=run_id, result={}
            )
        await session.commit()
        latest = await repo.latest_per_symbol("recommendation", ["AAPL", "MSFT"])
        assert {s: r.run_id for s, r in latest.items()} == {"AAPL": "a2", "MSFT": "m1"}


async def test_llm_usage_aggregates_on_postgres(pg_session_factory) -> None:
    """date() and string concatenation differ between SQLite and Postgres."""
    from datetime import timedelta

    from app.core.clock import utcnow
    from app.llm.pricing import TokenUsage
    from app.llm.recording import DbLLMCallRecorder, LLMCallRecord

    recorder = DbLLMCallRecorder(pg_session_factory)
    for call_id, agent in (("c1", "moat"), ("c2", "moat"), ("c3", "risk")):
        await recorder.record(
            LLMCallRecord(
                call_id=call_id,
                created_at=utcnow(),
                model="claude-haiku-4-5",
                prompt_name=agent,
                prompt_version="v1",
                status="ok",
                latency_ms=100,
                usage=TokenUsage(input_tokens=1000, output_tokens=100),
                cost_usd=0.0015,
                agent=agent,
            )
        )
    since = utcnow() - timedelta(days=1)
    async with pg_session_factory() as session:
        repo = LLMCallRepository(session)
        by_agent = {r.key: r.calls for r in await repo.usage(since=since, group_by="agent")}
        assert by_agent == {"moat": 2, "risk": 1}
        (day,) = await repo.usage(since=since, group_by="day")
        assert day.key == utcnow().date().isoformat() and day.calls == 3
        versions = {r.key for r in await repo.usage(since=since, group_by="prompt_version")}
        assert versions == {"moat@v1", "risk@v1"}
        # agent_runs gained the usage columns with defaults for existing rows
        await session.execute(
            text(
                "insert into agent_runs (run_id, agent_type, symbol, run_date, status, "
                "started_at, finished_at) values ('r', 'moat', 'AAPL', '2026-10-23', "
                "'completed', now(), now())"
            )
        )
        tokens = (
            await session.execute(text("select llm_calls, input_tokens from agent_runs"))
        ).one()
        assert tuple(tokens) == (0, 0)
