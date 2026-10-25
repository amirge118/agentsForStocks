import logging

import pytest

from app.llm import pricing
from app.llm.pricing import PRICES, Price, TokenUsage, cost_usd


@pytest.mark.unit
def test_cost_counts_every_token_kind() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )
    assert cost_usd("m", usage, {"m": Price(1.0, 5.0, 0.1, 1.25)}) == pytest.approx(7.35)
    assert usage.total_input == 3_000_000


@pytest.mark.unit
def test_known_models_have_prices() -> None:
    for model in ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-haiku-5-5"):
        assert model in PRICES
    one_k = TokenUsage(input_tokens=1000, output_tokens=200)
    assert cost_usd("claude-haiku-4-5", one_k) == pytest.approx(0.002)


@pytest.mark.unit
def test_unknown_model_costs_none_and_warns_once(caplog, monkeypatch) -> None:
    monkeypatch.setattr(pricing, "_warned", set())
    caplog.set_level(logging.WARNING, logger="app.llm.pricing")
    assert cost_usd("mystery-model", TokenUsage(input_tokens=10)) is None
    assert cost_usd("mystery-model", TokenUsage(input_tokens=10)) is None
    assert caplog.text.count("No price known") == 1
