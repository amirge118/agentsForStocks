from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.llm.prompt_loader import load_prompt
from app.llm.schema import output_schema
from app.schemas.signals import LLMSignal


def _message(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def _client(reply: object) -> tuple[LLMClient, AsyncMock]:
    sdk = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()), close=AsyncMock())
    if isinstance(reply, Exception):
        sdk.messages.create.side_effect = reply
    else:
        sdk.messages.create.return_value = reply
    return LLMClient(sdk, default_model="claude-haiku-4-5"), sdk.messages.create


@pytest.mark.unit
async def test_generate_returns_validated_model_and_sends_schema() -> None:
    llm, create = _client(_message('{"signal":"bullish","confidence":72,"reasoning":"Wide moat"}'))

    result = await llm.generate(system="s", prompt="p", schema=LLMSignal)

    assert result == LLMSignal(signal="bullish", confidence=72, reasoning="Wide moat")
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    fmt = kwargs["extra_body"]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["required"] == ["signal", "confidence", "reasoning"]


@pytest.mark.unit
async def test_generate_uses_model_override() -> None:
    llm, create = _client(_message('{"signal":"neutral","confidence":1,"reasoning":"r"}'))
    await llm.generate(system="s", prompt="p", schema=LLMSignal, model="claude-sonnet-4-6")
    assert create.await_args.kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.unit
@pytest.mark.parametrize(
    "reply",
    [
        _message('{"signal":"maybe","confidence":5,"reasoning":"r"}'),  # bad enum
        _message('{"signal":"bullish","confidence":500,"reasoning":"r"}'),  # out of range
        _message("{}", stop_reason="refusal"),
        _message('{"signal":', stop_reason="max_tokens"),
    ],
)
async def test_invalid_replies_raise_llm_error(reply: SimpleNamespace) -> None:
    llm, _ = _client(reply)
    with pytest.raises(LLMError):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)


@pytest.mark.unit
async def test_api_errors_raise_llm_error() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    status = anthropic.APIStatusError(
        "overloaded", response=httpx.Response(529, request=request), body=None
    )
    llm, _ = _client(status)
    with pytest.raises(LLMError, match="529"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)

    llm, _ = _client(anthropic.APIConnectionError(request=request))
    with pytest.raises(LLMError, match="unreachable"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)


class _Nested(BaseModel):
    title: str
    score: float = Field(ge=0, le=10)


class _Outer(BaseModel):
    items: list[_Nested] = Field(min_length=1)
    note: str = "x"


@pytest.mark.unit
def test_output_schema_is_strict_and_constraint_free() -> None:
    schema = output_schema(_Outer)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["items", "note"]
    nested = schema["$defs"]["_Nested"]
    assert nested["additionalProperties"] is False
    assert set(nested["properties"]) == {"title", "score"}  # a field named "title" survives
    assert "maximum" not in nested["properties"]["score"]
    assert "default" not in schema["properties"]["note"]


@pytest.mark.unit
def test_load_prompt_reads_markdown_file(tmp_path, monkeypatch) -> None:
    from app.llm import prompt_loader

    (tmp_path / "demo.md").write_text("  You are a demo.  \n")
    monkeypatch.setattr(prompt_loader, "_PROMPT_DIR", tmp_path)
    load_prompt.cache_clear()
    assert load_prompt("demo") == "You are a demo."
    load_prompt.cache_clear()
