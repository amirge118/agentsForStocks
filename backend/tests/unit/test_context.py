import asyncio

import pytest

from app.core.context import bind, bind_run, current_fields, current_usage, note_fallback


@pytest.mark.unit
def test_bind_nests_and_restores() -> None:
    assert current_fields() == {}
    with bind(pipeline_run_id="p1"):
        with bind(agent="moat", symbol=None):  # None values are not bound
            assert current_fields() == {"pipeline_run_id": "p1", "agent": "moat"}
        assert current_fields() == {"pipeline_run_id": "p1"}
    assert current_fields() == {}


@pytest.mark.unit
def test_bind_run_collects_usage_and_fallbacks() -> None:
    note_fallback()  # outside a run: ignored
    assert current_usage() is None
    with bind_run(run_id="r1", agent="moat") as usage:
        assert current_usage() is usage
        assert current_fields()["run_id"] == "r1"
        note_fallback()
    assert usage.llm_fallbacks == 1
    assert current_usage() is None


@pytest.mark.unit
async def test_tasks_inherit_parent_context_but_keep_their_own() -> None:
    seen: list[dict[str, str]] = []

    async def agent(name: str) -> None:
        with bind_run(agent=name):
            await asyncio.sleep(0)  # interleave with the other task
            seen.append(current_fields())

    with bind(pipeline_run_id="p1"):
        await asyncio.gather(agent("moat"), agent("risk"))

    assert sorted(f["agent"] for f in seen) == ["moat", "risk"]
    assert all(f["pipeline_run_id"] == "p1" for f in seen)
