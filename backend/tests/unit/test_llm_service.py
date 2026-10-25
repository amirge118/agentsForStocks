from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.signals import LLMSignal
from app.services import llm_service


def _fake_client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(text=text)])
    return client


@pytest.mark.unit
async def test_call_claude_parses_signal_without_agent_fields(monkeypatch) -> None:
    """Regression: Claude only returns signal/confidence/reasoning — that must not fall back."""
    reply = '{"signal": "bullish", "confidence": 80, "reasoning": "Strong moat"}'
    monkeypatch.setattr(llm_service, "_get_client", lambda: _fake_client(reply))

    result = await llm_service.call_claude("sys", "user", response_model=LLMSignal)

    assert result == LLMSignal(signal="bullish", confidence=80, reasoning="Strong moat")


@pytest.mark.unit
async def test_call_claude_falls_back_to_neutral_on_garbage(monkeypatch) -> None:
    monkeypatch.setattr(llm_service, "_get_client", lambda: _fake_client("not json"))

    result = await llm_service.call_claude("sys", "user", response_model=LLMSignal)

    assert result.signal == "neutral"
    assert result.confidence == 0.0
