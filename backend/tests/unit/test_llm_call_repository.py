from datetime import datetime, timedelta

import pytest

from app.core.clock import utcnow
from app.llm.pricing import TokenUsage
from app.llm.recording import DbLLMCallRecorder, LedgerUsage, LLMCallRecord, prompt_version
from app.repositories.llm_calls import LLMCallRepository


def _record(
    call_id: str,
    *,
    agent: str = "moat",
    model: str = "claude-haiku-4-5",
    status: str = "ok",
    created_at: datetime | None = None,
    cost: float | None = 0.002,
    run_id: str = "r1",
    provider: str | None = "anthropic",
) -> LLMCallRecord:
    return LLMCallRecord(
        call_id=call_id,
        created_at=created_at or utcnow(),
        model=model,
        prompt_name=agent,
        prompt_version="abc123",
        status=status,
        latency_ms=120,
        usage=TokenUsage(input_tokens=1000, output_tokens=200, cache_read_tokens=50),
        cost_usd=cost,
        run_id=run_id,
        pipeline_run_id="p1",
        agent=agent,
        symbol="AAPL",
        provider=provider,
        system_prompt="sys",
        prompt="user",
        response='{"signal":"bullish"}',
    )


@pytest.mark.unit
def test_prompt_version_is_stable_and_short() -> None:
    assert prompt_version("You are a moat analyst.") == prompt_version("You are a moat analyst.")
    assert prompt_version("a") != prompt_version("b")
    assert len(prompt_version("a")) == 12


@pytest.mark.unit
async def test_recorder_stores_calls_and_repository_lists_them(session_factory) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    await recorder.record(_record("c1"))
    await recorder.record(_record("c2", agent="risk", run_id="r2"))

    async with session_factory() as session:
        repo = LLMCallRepository(session)
        assert [c.call_id for c in await repo.list(run_id="r1")] == ["c1"]
        assert {c.agent for c in await repo.list(pipeline_run_id="p1")} == {"moat", "risk"}
        (call,) = await repo.list(agent="risk")
        assert (call.input_tokens, call.cache_read_tokens, call.prompt) == (1000, 50, "user")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("group_by", "keys"),
    [
        ("agent", {"moat", "risk"}),
        ("model", {"claude-haiku-4-5", "claude-sonnet-4-6"}),
        ("prompt_version", {"moat@abc123", "risk@abc123"}),
    ],
)
async def test_usage_groups_and_sums(session_factory, group_by: str, keys: set[str]) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    await recorder.record(_record("c1"))
    await recorder.record(_record("c2", status="error", cost=None))
    await recorder.record(_record("c3", agent="risk", model="claude-sonnet-4-6", cost=0.01))
    await recorder.record(_record("old", created_at=utcnow() - timedelta(days=30)))

    async with session_factory() as session:
        rows = await LLMCallRepository(session).usage(
            since=utcnow() - timedelta(days=7), group_by=group_by
        )
    assert {r.key for r in rows} == keys
    assert sum(r.calls for r in rows) == 3  # the 30-day-old call is outside the window
    assert sum(r.errors for r in rows) == 1
    assert sum(r.input_tokens for r in rows) == 3000
    assert sum(r.cost_usd for r in rows) == pytest.approx(0.012)
    assert rows[0].cost_usd >= rows[-1].cost_usd  # most expensive first


@pytest.mark.unit
async def test_usage_by_day(session_factory) -> None:
    await DbLLMCallRecorder(session_factory).record(_record("c1"))
    async with session_factory() as session:
        (row,) = await LLMCallRepository(session).usage(
            since=utcnow() - timedelta(days=1), group_by="day"
        )
    assert row.key == utcnow().date().isoformat()


@pytest.mark.unit
async def test_delete_older_than(session_factory) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    await recorder.record(_record("new"))
    await recorder.record(_record("old", created_at=utcnow() - timedelta(days=100)))
    async with session_factory() as session:
        repo = LLMCallRepository(session)
        assert await repo.delete_older_than(utcnow() - timedelta(days=90)) == 1
        await session.commit()
        assert [c.call_id for c in await repo.list()] == ["new"]


@pytest.mark.unit
async def test_recorder_failure_is_logged_not_raised(caplog) -> None:
    def broken_factory():
        raise RuntimeError("db down")

    await DbLLMCallRecorder(broken_factory).record(_record("c1"))
    assert "Could not record LLM call" in caplog.text


@pytest.mark.unit
async def test_provider_totals_seed_the_free_tier_quotas(session_factory) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    now = utcnow()
    for call_id, provider, at in (
        ("g1", "gemini", now),
        ("g2", "gemini", now - timedelta(hours=1)),
        ("g-old", "gemini", now - timedelta(days=2)),
        ("q1", "groq", now),
    ):
        await recorder.record(_record(call_id, provider=provider, created_at=at))
    since = now - timedelta(hours=3)
    # 1000 input + 200 output + 50 cache read per call
    assert await LedgerUsage(session_factory)("gemini", since) == (2, 2500)
    assert await LedgerUsage(session_factory)("cerebras", since) == (0, 0)


@pytest.mark.unit
async def test_usage_by_provider_labels_calls_from_before_the_column(
    session_factory, db_session
) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    await recorder.record(_record("a", provider="gemini", cost=0.0))
    await recorder.record(_record("b", provider="gemini", cost=0.0))
    await recorder.record(_record("c", provider=None))
    rows = await LLMCallRepository(db_session).usage(
        since=utcnow() - timedelta(days=1), group_by="provider"
    )
    assert sorted((r.key, r.calls) for r in rows) == [("(unknown)", 1), ("gemini", 2)]
