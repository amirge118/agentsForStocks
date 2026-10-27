"""
Prompt snapshots: the exact system and user prompt each agent sends to Claude for
the baseline scenario, stored in tests/snapshots/prompts/<agent>.txt. A change to
a prompt — wording, data formatting, a dropped field — shows up as a diff in the
PR. After an intended change, refresh the files:

    UPDATE_SNAPSHOTS=1 pytest tests/unit/agents/test_prompt_snapshots.py

Also a size budget per call, so prompts can't quietly grow (tokens are money).
"""

import os
from datetime import date
from pathlib import Path

import pytest

from app.agents.catalog import load_agents
from tests import scenarios
from tests.factories import FakeLLM, FakeOutcomes, FakeResults, make_context

RUN_DATE = date(2026, 10, 23)
SNAPSHOTS = Path(__file__).resolve().parents[2] / "snapshots" / "prompts"
# ~4 characters per token: 12k characters ≈ 3k input tokens per call
MAX_PROMPT_CHARS = 12_000

registry = load_agents()


def _analysts() -> FakeResults:
    return FakeResults(
        {
            name: {"signal": "bullish", "confidence": 70.0, "reasoning": f"{name} looks fine"}
            for name in registry.weights()
        }
    )


async def _prompts(name: str) -> tuple[str, list[dict]]:
    base = scenarios.baseline()
    llm = FakeLLM()
    ctx = make_context(
        yfinance=base.yfinance,
        fmp=base.fmp,
        edgar=base.edgar,
        llm=llm,
        results=_analysts(),
        outcomes=FakeOutcomes(),
    )
    agent = registry.get(name).agent_cls(ctx)
    data = await agent.fetch("AAPL", RUN_DATE)
    await agent.analyze("AAPL", data, ["Earlier run: steady margins"])
    blocks = [
        f"### call {i + 1}: prompt_name={c['prompt_name']} model={c['model'] or 'default'}\n"
        f"--- system\n{c['system']}\n--- user\n{c['prompt']}\n"
        for i, c in enumerate(llm.calls)
    ]
    return "\n".join(blocks), llm.calls


@pytest.mark.unit
@pytest.mark.parametrize("name", registry.names())
async def test_prompt_matches_snapshot(name: str) -> None:
    rendered, calls = await _prompts(name)
    assert calls, f"{name} made no LLM call on the baseline scenario"
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    assert path.exists(), f"missing snapshot — run: UPDATE_SNAPSHOTS=1 pytest {__file__}"
    assert rendered == path.read_text(
        encoding="utf-8"
    ), f"{name}'s prompt changed. If intended: UPDATE_SNAPSHOTS=1 pytest {__file__}"


@pytest.mark.unit
@pytest.mark.parametrize("name", registry.names())
async def test_prompt_size_budget(name: str) -> None:
    _, calls = await _prompts(name)
    for call in calls:
        size = len(call["system"]) + len(call["prompt"])
        assert size <= MAX_PROMPT_CHARS, f"{name}: {size} chars > budget {MAX_PROMPT_CHARS}"


@pytest.mark.unit
async def test_prompts_carry_the_recalled_memory() -> None:
    for name in ("moat", "valuation", "technicals"):
        _, calls = await _prompts(name)
        assert "Earlier run: steady margins" in calls[-1]["prompt"]
