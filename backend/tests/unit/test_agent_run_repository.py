from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.agent_run import AgentRun
from app.repositories.agent_runs import AgentRunRepository

T0 = datetime(2026, 10, 23, 22, 0, tzinfo=UTC)


def _run(i: int, symbol: str, status: str, pipeline: str = "p1") -> AgentRun:
    start = T0 + timedelta(minutes=i)
    return AgentRun(
        run_id=f"r{i}",
        pipeline_run_id=pipeline,
        agent_type="moat",
        symbol=symbol,
        run_date=date(2026, 10, 23),
        status=status,
        started_at=start,
        finished_at=start,
    )


@pytest.mark.unit
async def test_list_filters_and_orders_newest_first(db_session) -> None:
    repo = AgentRunRepository(db_session)
    for run in (
        _run(1, "AAPL", "completed"),
        _run(2, "AAPL", "failed"),
        _run(3, "MSFT", "completed", pipeline="p2"),
    ):
        repo.add(run)
    await db_session.commit()

    assert [r.run_id for r in await repo.list()] == ["r3", "r2", "r1"]
    assert [r.run_id for r in await repo.list(symbol="AAPL", status="failed")] == ["r2"]
    assert [r.run_id for r in await repo.list(pipeline_run_id="p2")] == ["r3"]
    assert len(await repo.list(run_date=date(2026, 10, 23), limit=2)) == 2
    assert await repo.list(run_date=date(2026, 1, 1)) == []
