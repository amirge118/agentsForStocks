from datetime import date

import pytest

from app.agents.compliance import review_stored
from app.ops.compliance_backfill import backfill_compliance
from app.repositories.agent_results import AgentResultRepository

OLD = {"signal": "bullish", "confidence": 80.0, "reasoning": "Strong brand.", "summary": "s"}
PROMISE = {
    "signal": "bullish",
    "confidence": 90.0,
    "reasoning": "A guaranteed winner.",
    "summary": "Moat: bullish (90%) — A guaranteed winner.",
}


@pytest.mark.unit
def test_review_stored_adds_the_review_once() -> None:
    reviewed = review_stored("moat", "AAPL", {**OLD, "moat_type": "brand"})
    assert reviewed["compliance"]["status"] == "pass"
    assert reviewed["moat_type"] == "brand"  # the agent's own fields stay
    assert review_stored("moat", "AAPL", reviewed) is None

    failed = review_stored("moat", "AAPL", PROMISE)
    assert failed["compliance"]["status"] == "fail"
    assert "guaranteed" not in failed["reasoning"] and "guaranteed" not in failed["summary"]
    assert failed["compliance"]["original_reasoning"] == "A guaranteed winner."


@pytest.mark.unit
async def test_backfill_reviews_old_results_in_place(session_factory, db_session) -> None:
    repo = AgentResultRepository(db_session)
    for agent, result in (("moat", OLD), ("risk", PROMISE)):
        await repo.upsert(
            agent_type=agent, symbol="AAPL", run_date=date(2026, 9, 1), run_id="r", result=result
        )
    await db_session.commit()

    dry = await backfill_compliance(session_factory, dry_run=True)
    assert (dry.scanned, dry.statuses) == (2, {"pass": 1, "fail": 1})
    assert dry.render() == "2 stored results, would review 2 (fail 1, pass 1)"

    report = await backfill_compliance(session_factory)
    assert report.statuses == {"pass": 1, "fail": 1}
    async with session_factory() as session:
        rows = {r.agent_type: r.result_json for r in await AgentResultRepository(session).all()}
    assert rows["risk"]["compliance"]["status"] == "fail"
    assert "guaranteed" not in rows["risk"]["reasoning"]
    again = await backfill_compliance(session_factory)
    assert again.statuses == {}  # idempotent
