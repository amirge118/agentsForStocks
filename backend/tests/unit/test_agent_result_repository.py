from datetime import date

import pytest

from app.repositories.agent_results import AgentResultRepository

D1 = date(2026, 3, 24)
D2 = date(2026, 3, 25)


@pytest.mark.unit
async def test_upsert_is_idempotent_per_agent_symbol_date(db_session) -> None:
    repo = AgentResultRepository(db_session)
    await repo.upsert(agent_type="moat", symbol="AAPL", run_date=D1, run_id="a", result={"v": 1})
    await repo.upsert(agent_type="moat", symbol="AAPL", run_date=D1, run_id="b", result={"v": 2})
    await db_session.commit()

    assert await repo.exists("moat", "AAPL", D1)
    assert not await repo.exists("moat", "AAPL", D2)
    assert await repo.get_for_date("AAPL", D1) == {"moat": {"v": 2}}


@pytest.mark.unit
async def test_get_for_date_filters_agent_types(db_session) -> None:
    repo = AgentResultRepository(db_session)
    for agent in ("moat", "risk", "growth"):
        await repo.upsert(
            agent_type=agent, symbol="AAPL", run_date=D1, run_id="r", result={"a": agent}
        )
    await db_session.commit()

    assert set(await repo.get_for_date("AAPL", D1, agent_types=["moat", "risk"])) == {
        "moat",
        "risk",
    }


@pytest.mark.unit
async def test_latest_for_symbol_orders_newest_first(db_session) -> None:
    repo = AgentResultRepository(db_session)
    await repo.upsert(agent_type="moat", symbol="AAPL", run_date=D1, run_id="r1", result={})
    await repo.upsert(agent_type="moat", symbol="AAPL", run_date=D2, run_id="r2", result={})
    await repo.upsert(agent_type="risk", symbol="AAPL", run_date=D2, run_id="r3", result={})
    await repo.upsert(agent_type="moat", symbol="MSFT", run_date=D2, run_id="r4", result={})
    await db_session.commit()

    rows = await repo.latest_for_symbol("AAPL")
    assert [(r.run_date, r.agent_type) for r in rows] == [(D2, "moat"), (D2, "risk"), (D1, "moat")]
    assert [r.run_id for r in await repo.latest_for_symbol("AAPL", agent_type="moat", limit=1)] == [
        "r2"
    ]
