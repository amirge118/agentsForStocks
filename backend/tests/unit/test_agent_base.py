from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents.base import AgentBase
from app.agents.moat_agent import MoatAgent
from app.models.agent_result import AgentResult


class _EchoAgent(AgentBase):
    agent_type = "echo"

    def __init__(self, db, knowledge, payload: dict) -> None:
        super().__init__(db=db, knowledge=knowledge)
        self.payload = payload
        self.fetch_calls = 0

    async def fetch_data(self, symbol: str) -> dict:
        self.fetch_calls += 1
        return {"symbol": symbol}

    async def analyze(self, data: dict, prior_context: list[str]) -> dict:
        return {**self.payload, "symbol": data["symbol"]}


def _knowledge() -> AsyncMock:
    knowledge = AsyncMock()
    knowledge.recall_for_symbol.return_value = []
    return knowledge


@pytest.mark.unit
async def test_run_stores_result_and_skips_rerun_same_day(db_session) -> None:
    agent = _EchoAgent(db_session, _knowledge(), {"signal": "bullish", "summary": "s"})

    await agent.run("AAPL")
    await agent.run("AAPL")

    rows = (await db_session.execute(select(AgentResult))).scalars().all()
    assert len(rows) == 1
    assert rows[0].result_json["signal"] == "bullish"
    assert agent.fetch_calls == 1  # second run short-circuited by idempotency check


@pytest.mark.unit
async def test_store_result_upserts_instead_of_duplicating(db_session) -> None:
    agent = _EchoAgent(db_session, _knowledge(), {})

    await agent.store_result("MSFT", run_id="r1", result={"signal": "bearish"})
    await agent.store_result("MSFT", run_id="r2", result={"signal": "bullish"})

    rows = (await db_session.execute(select(AgentResult))).scalars().all()
    assert len(rows) == 1
    assert rows[0].run_id == "r2"
    assert rows[0].result_json == {"signal": "bullish"}


@pytest.mark.unit
async def test_safe_write_swallows_knowledge_errors(db_session) -> None:
    agent = _EchoAgent(db_session, _knowledge(), {})
    failing = AsyncMock(side_effect=RuntimeError("openviking down"))

    await agent._safe_write(failing())  # must not raise


@pytest.mark.unit
async def test_subclass_store_learnings_no_longer_crashes(db_session) -> None:
    """Regression: MoatAgent called self._safe_write, which did not exist on AgentBase."""
    knowledge = _knowledge()
    agent = MoatAgent(db=db_session, knowledge=knowledge)

    await agent.store_learnings(
        "AAPL", {"signal": "bullish", "moat_keywords": ["patent"], "summary": "Moat: bullish"}
    )

    knowledge.store_pattern.assert_awaited_once()
    knowledge.store_analysis_result.assert_awaited_once()
