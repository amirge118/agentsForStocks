from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, update

from app.agents.base import neutral_fallback
from app.agents.registry import registry
from app.agents.runner import AgentRunner
from app.core.clock import utcnow
from app.knowledge.store import NullKnowledgeStore
from app.llm.replies import StoredReplies, reply_key
from app.models.agent_run import AgentRun
from app.models.llm_reply import LLMReply
from tests.factories import FakeLLM, make_context

DAY = date(2026, 11, 3)


def _agent(llm: FakeLLM, replies: StoredReplies | None):
    return registry.get("technicals").agent_cls(make_context(llm=llm, replies=replies))


@pytest.mark.unit
def test_the_key_changes_with_anything_that_shapes_the_reply() -> None:
    base = reply_key(system="s", prompt="p", model="m")
    assert base == reply_key(model="m", prompt="p", system="s")
    assert base != reply_key(system="s", prompt="other", model="m")
    assert base != reply_key(system="other", prompt="p", model="m")
    assert base != reply_key(system="s", prompt="p", model="other")


@pytest.mark.unit
async def test_the_same_prompt_reuses_the_reply_and_a_new_one_asks(session_factory) -> None:
    llm = FakeLLM()
    agent = _agent(llm, StoredReplies(session_factory, max_age_days=30))
    fallback = neutral_fallback()

    first = await agent.judge("the same data", fallback=fallback)
    second = await agent.judge("the same data", fallback=fallback)
    assert len(llm.calls) == 1
    assert second == first

    await agent.judge("new data", fallback=fallback)
    assert len(llm.calls) == 2


@pytest.mark.unit
async def test_a_changed_setup_doesnt_reuse(session_factory) -> None:
    replies = StoredReplies(session_factory, max_age_days=30)
    llm = FakeLLM()
    await _agent(llm, replies).judge("data", fallback=neutral_fallback())

    other = FakeLLM()
    other.model_scope = lambda provider=None: "another-model"  # type: ignore[method-assign]
    await _agent(other, replies).judge("data", fallback=neutral_fallback())
    assert len(other.calls) == 1


@pytest.mark.unit
async def test_a_fallback_is_never_stored(session_factory) -> None:
    replies = StoredReplies(session_factory, max_age_days=30)
    down = FakeLLM(fail=True)
    fallback = neutral_fallback()
    assert await _agent(down, replies).judge("data", fallback=fallback) == fallback

    up = FakeLLM()
    await _agent(up, replies).judge("data", fallback=fallback)
    assert len(up.calls) == 1


@pytest.mark.unit
async def test_an_expired_reply_is_ignored_and_pruned(session_factory) -> None:
    replies = StoredReplies(session_factory, max_age_days=30)
    await replies.put("k", "moat", "{}")
    assert await replies.get("k") == "{}"

    async with session_factory() as session:
        await session.execute(update(LLMReply).values(created_at=utcnow() - timedelta(days=31)))
        await session.commit()

    assert await replies.get("k") is None
    assert await replies.prune() == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(LLMReply)) == 0


@pytest.mark.unit
async def test_a_reply_in_an_older_shape_asks_the_model_again(session_factory) -> None:
    replies = StoredReplies(session_factory, max_age_days=30)
    llm = FakeLLM()
    agent = _agent(llm, replies)
    await agent.judge("data", fallback=neutral_fallback())
    async with session_factory() as session:
        await session.execute(update(LLMReply).values(reply='{"unexpected": true}'))
        await session.commit()

    await agent.judge("data", fallback=neutral_fallback())
    assert len(llm.calls) == 2


@pytest.mark.unit
async def test_a_new_day_reuses_and_force_asks_and_the_run_records_it(session_factory) -> None:
    replies = StoredReplies(session_factory, max_age_days=30)
    llm = FakeLLM()
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    agent = _agent(llm, replies)

    assert (await runner.run(agent, "AAPL", DAY)).status == "completed"
    assert len(llm.calls) == 1

    next_day = await runner.run(agent, "AAPL", DAY + timedelta(days=1))
    assert next_day.status == "completed"
    assert next_day.result is not None  # a real result for the new date
    assert next_day.usage.llm_reused == 1 and next_day.usage.llm_calls == 0
    assert len(llm.calls) == 1

    forced = await runner.run(agent, "AAPL", DAY + timedelta(days=1), force=True)
    assert forced.usage.llm_reused == 0
    assert len(llm.calls) == 2

    async with session_factory() as session:
        reused = await session.scalars(select(AgentRun.llm_reused).order_by(AgentRun.started_at))
        assert list(reused) == [0, 1, 0]
