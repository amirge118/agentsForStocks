import pytest

from app.agents.moat import MoatAgent
from app.container import build_container
from app.core.config import Settings
from app.knowledge.openviking_store import OpenVikingStore
from app.knowledge.store import NullKnowledgeStore
from app.pipeline.settlement import OutcomeSettler


@pytest.mark.unit
async def test_build_container_wires_agents(session_factory) -> None:
    container = build_container(Settings(openviking_enabled=False), session_factory)
    try:
        assert isinstance(container.knowledge, NullKnowledgeStore)
        agent = container.build_agent("moat")
        assert isinstance(agent, MoatAgent)
        assert agent.ctx is container.agent_context
        assert container.agent_context.reasoning_model == Settings().llm_reasoning_model
        assert isinstance(container.settler, OutcomeSettler)
    finally:
        await container.aclose()


@pytest.mark.unit
async def test_openviking_store_used_when_enabled(session_factory) -> None:
    container = build_container(Settings(openviking_enabled=True), session_factory)
    assert isinstance(container.knowledge, OpenVikingStore)
    await container.aclose()
