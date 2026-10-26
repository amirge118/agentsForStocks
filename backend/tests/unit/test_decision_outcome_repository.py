from datetime import date

import pytest

from app.repositories.agent_results import AgentResultRepository
from app.repositories.decision_outcomes import DecisionOutcomeRepository


async def _judge(session, symbol: str, run_date: date) -> None:
    await AgentResultRepository(session).upsert(
        agent_type="risk", symbol=symbol, run_date=run_date, run_id="r", result={}
    )


@pytest.mark.unit
async def test_seed_adds_missing_horizons_only(db_session) -> None:
    await _judge(db_session, "AAPL", date(2026, 10, 5))
    repo = DecisionOutcomeRepository(db_session)

    assert await repo.seed_pending((5, 20), "SPY") == 2
    assert await repo.seed_pending((5, 20), "SPY") == 0
    # A new horizon backfills just that horizon
    assert await repo.seed_pending((5, 20, 60), "SPY") == 1
    pending = await repo.pending()
    assert [(r.horizon_days, r.status, r.attempts) for r in pending] == [
        (5, "pending", 0),
        (20, "pending", 0),
        (60, "pending", 0),
    ]


@pytest.mark.unit
async def test_pending_is_ordered_and_filtered(db_session) -> None:
    await _judge(db_session, "MSFT", date(2026, 10, 6))
    await _judge(db_session, "AAPL", date(2026, 10, 6))
    await _judge(db_session, "AAPL", date(2026, 10, 5))
    repo = DecisionOutcomeRepository(db_session)
    await repo.seed_pending((5,), "SPY", symbols=["AAPL"])

    rows = await repo.pending()
    assert [(r.symbol, r.decision_date) for r in rows] == [
        ("AAPL", date(2026, 10, 5)),
        ("AAPL", date(2026, 10, 6)),
    ]
    assert await repo.pending(symbols=["MSFT"]) == []
    rows[0].status = "settled"
    assert len(await repo.pending()) == 1
