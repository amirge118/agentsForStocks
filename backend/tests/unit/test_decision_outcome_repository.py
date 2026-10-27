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


async def _settled(session, symbol: str, day: date, alpha: float, horizon: int = 20) -> None:
    from app.models.decision_outcome import DecisionOutcome

    session.add(
        DecisionOutcome(
            symbol=symbol,
            decision_date=day,
            horizon_days=horizon,
            benchmark="SPY",
            status="settled",
            exit_date=date(2026, 12, 1),
            raw_return=alpha + 0.01,
            alpha=alpha,
        )
    )


@pytest.mark.unit
async def test_scored_calls_join_every_agent_and_filter(db_session) -> None:
    from app.models.decision_outcome import DecisionOutcome

    results = AgentResultRepository(db_session)
    for symbol, day in (("AAPL", date(2026, 10, 5)), ("MSFT", date(2026, 10, 6))):
        for agent, signal in (("recommendation", "bullish"), ("outcome_review", "neutral")):
            await results.upsert(
                agent_type=agent,
                symbol=symbol,
                run_date=day,
                run_id="r",
                result={"signal": signal, "confidence": 70.0},
            )
        await _settled(db_session, symbol, day, 0.02)
    db_session.add(
        DecisionOutcome(
            symbol="AAPL",
            decision_date=date(2026, 10, 7),
            horizon_days=20,
            benchmark="SPY",
            status="pending",
        )
    )
    repo = DecisionOutcomeRepository(db_session)

    rows = await repo.scored_calls(20, exclude_agents=["outcome_review"])
    assert [(a, c.symbol) for a, c in rows] == [
        ("recommendation", "MSFT"),
        ("recommendation", "AAPL"),
    ]
    assert rows[0][1].signal == "bullish" and rows[0][1].confidence == 70.0
    assert len(await repo.scored_calls(20)) == 4
    assert [
        c.symbol for _, c in await repo.scored_calls(20, agent="recommendation", symbol="AAPL")
    ] == ["AAPL"]
    assert len(await repo.scored_calls(20, since=date(2026, 10, 6))) == 2
    assert await repo.scored_calls(5) == []
    assert await repo.status_counts(20) == {"settled": 2, "pending": 1}
    assert await repo.status_counts(20, symbol="MSFT") == {"settled": 1}
