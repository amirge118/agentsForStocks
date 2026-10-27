"""Guards on the registry as a whole — catch wiring mistakes when an agent is added."""

import pytest

from app.agents.base import AnalysisResult
from app.agents.catalog import load_agents
from app.agents.recommendation import INPUT_AGENTS
from app.llm.prompt_loader import load_prompt

registry = load_agents()


@pytest.mark.unit
def test_all_agents_registered() -> None:
    assert len(registry.names()) == 14


@pytest.mark.unit
def test_recommendation_inputs_match_weighted_agents() -> None:
    assert set(INPUT_AGENTS) == set(registry.weights())
    assert set(registry.get("recommendation").depends_on) == {*INPUT_AGENTS, "outcome_review"}
    assert sum(registry.weights().values()) == 100


@pytest.mark.unit
def test_recommendation_runs_last() -> None:
    assert registry.execution_levels()[-1] == ["recommendation"]


@pytest.mark.unit
@pytest.mark.parametrize("name", registry.names())
def test_every_agent_has_prompt_and_result_model(name: str) -> None:
    spec = registry.get(name)
    assert load_prompt(name)
    assert issubclass(spec.agent_cls.result_model, AnalysisResult)
    assert spec.description


@pytest.mark.unit
def test_funds_run_only_the_market_agents() -> None:
    registry = load_agents()
    fund = {name for level in registry.execution_levels(fund=True) for name in level}
    assert fund == {"market_scanner", "technicals", "sentiment"}
    assert "recommendation" in registry.company_only()  # no BUY/SELL from price data alone
