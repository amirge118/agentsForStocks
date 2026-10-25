"""Profiles change how an agent calls the model — provider, model, skills, budget, on/off."""

from datetime import date

import pytest
from sqlalchemy import select

from app.agents.catalog import load_agents
from app.agents.runner import AgentRunner
from app.knowledge.store import NullKnowledgeStore
from app.llm.profiles import ProfileBook
from app.models.agent_run import AgentRun
from tests.factories import FakeLLM, FakeResults, make_context

RUN_DATE = date(2026, 10, 23)
registry = load_agents()


async def _run(name: str, overrides: dict, llm: FakeLLM | None = None, **ctx):
    llm = llm or FakeLLM()
    agent = registry.get(name).agent_cls(
        make_context(llm=llm, profiles=ProfileBook(overrides), **ctx)
    )
    data = await agent.fetch("AAPL", RUN_DATE)
    return await agent.analyze("AAPL", data, []), llm


@pytest.mark.unit
async def test_llm_can_be_switched_off_for_an_agent(session_factory, db_session) -> None:
    llm = FakeLLM()
    agent = registry.get("technicals").agent_cls(
        make_context(llm=llm, profiles=ProfileBook({"technicals": {"use_llm": False}}))
    )
    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)

    assert llm.calls == []
    assert outcome.result is not None
    assert outcome.result.reasoning.startswith("Rule-based (LLM off for this agent)")
    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert (run.llm_calls, run.llm_fallbacks) == (0, 0)  # a choice, not an outage


@pytest.mark.unit
async def test_skills_are_added_to_the_system_prompt_and_label_the_call() -> None:
    _, llm = await _run("moat", {"moat": {"skills": ["moat_evidence", "confidence_calibration"]}})
    (call,) = llm.calls
    assert call["system"].startswith("You are a competitive-analysis expert")
    assert "A moat needs evidence" in call["system"]
    assert "Never exceed 95" in call["system"]
    assert call["prompt_name"] == "moat+moat_evidence+confidence_calibration"


@pytest.mark.unit
async def test_a_secondary_prompt_can_use_the_cheap_provider() -> None:
    _, llm = await _run("sentiment", {"news_sentiment": {"provider": "alt", "max_tokens": 128}})
    by_prompt = {c["prompt_name"]: c for c in llm.calls}
    assert by_prompt["news_sentiment"]["provider"] == "alt"
    assert by_prompt["news_sentiment"]["max_tokens"] == 128
    assert by_prompt["sentiment"]["provider"] == "anthropic"  # the main judgement stays on Claude


@pytest.mark.unit
async def test_claude_model_hints_are_not_sent_to_another_provider() -> None:
    analysts = FakeResults(
        {
            n: {"signal": "bullish", "confidence": 70.0, "reasoning": "ok"}
            for n in registry.weights()
        }
    )
    _, on_claude = await _run("recommendation", {}, results=analysts)
    assert on_claude.calls[0]["model"] == "reasoning-model"

    _, on_alt = await _run("recommendation", {"*": {"provider": "alt"}}, results=analysts)
    assert (on_alt.calls[0]["provider"], on_alt.calls[0]["model"]) == ("alt", None)

    _, pinned = await _run(
        "recommendation", {"recommendation": {"provider": "alt", "model": "big"}}, results=analysts
    )
    assert pinned.calls[0]["model"] == "big"


@pytest.mark.unit
async def test_prompt_variants_select_another_prompt_file(tmp_path, monkeypatch) -> None:
    from app.llm import prompt_loader

    (tmp_path / "technicals.md").write_text("Original prompt.")
    (tmp_path / "technicals_v2.md").write_text("Variant prompt.")
    monkeypatch.setattr(prompt_loader, "_PROMPT_DIR", tmp_path)
    prompt_loader.load_prompt.cache_clear()
    try:
        _, llm = await _run("technicals", {"technicals": {"prompt": "technicals_v2"}})
    finally:
        prompt_loader.load_prompt.cache_clear()
    assert llm.calls[0]["system"] == "Variant prompt."
    assert llm.calls[0]["prompt_name"] == "technicals_v2"
