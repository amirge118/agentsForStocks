"""
All 14 real agents through the real orchestrator, runner and SQLite DB.
Only the network-facing providers and the LLM are faked.
"""

from datetime import date

import pytest

from app.agents.catalog import load_agents
from app.agents.runner import AgentRunner, SessionResultsReader
from app.knowledge.store import NullKnowledgeStore
from app.pipeline.orchestrator import PipelineOrchestrator
from app.repositories.agent_results import AgentResultRepository
from tests.factories import FakeLLM, make_context

RUN_DATE = date(2026, 10, 23)


@pytest.mark.integration
async def test_full_pipeline_produces_a_recommendation(concurrent_session_factory) -> None:
    registry = load_agents()
    ctx = make_context(llm=FakeLLM(), results=SessionResultsReader(concurrent_session_factory))
    orchestrator = PipelineOrchestrator(
        AgentRunner(concurrent_session_factory, NullKnowledgeStore()),
        registry,
        build_agent=lambda name: registry.get(name).agent_cls(ctx),
        today=lambda: RUN_DATE,  # a live run on RUN_DATE, not a historical one
    )

    report = await orchestrator.run(["AAPL"], run_date=RUN_DATE)

    assert report.counts == {"completed": 14}
    async with concurrent_session_factory() as session:
        stored = await AgentResultRepository(session).get_for_date("AAPL", RUN_DATE)
    assert set(stored) == set(registry.names())
    recommendation = stored["recommendation"]
    assert recommendation["agents_available"] == 8
    assert recommendation["agents_missing"] == []
    assert recommendation["action"] == "BUY"  # every analyst judged bullish at 70%
    assert recommendation["weighted_score"] == pytest.approx(70.0)
