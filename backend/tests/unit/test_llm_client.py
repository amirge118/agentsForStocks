from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.llm.mcp import MCP_BETA, McpServer
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


def _mcp_client(content: list) -> tuple[LLMClient, AsyncMock, list]:
    """SDK fake exposing with_options(...).beta.messages.create, recording the options."""
    beta_create = AsyncMock(return_value=SimpleNamespace(stop_reason="end_turn", content=content))
    plain_create = AsyncMock()
    options: list[dict] = []

    def with_options(**kwargs):
        options.append(kwargs)
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=beta_create)))

    sdk = SimpleNamespace(messages=SimpleNamespace(create=plain_create), with_options=with_options)
    return LLMClient(sdk, default_model="m"), beta_create, options


FACTSET = McpServer(
    name="factset", url="https://mcp.factset.com/content/v1", authorization_token="tok"
)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


@pytest.mark.unit
async def test_generate_returns_validated_model_and_sends_schema() -> None:
    llm, create = _client(_message('{"signal":"bullish","confidence":72,"reasoning":"Wide moat"}'))

    result = await llm.generate(system="s", prompt="p", schema=LLMSignal)

    assert result == LLMSignal(signal="bullish", confidence=72, reasoning="Wide moat")
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert "extra_body" not in kwargs  # typed parameter since anthropic 1.x
    fmt = kwargs["output_config"]["format"]
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
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    status = anthropic.APIStatusError(
        "overloaded", response=httpx2.Response(529, request=request), body=None
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


@pytest.mark.unit
async def test_mcp_request_sends_servers_toolsets_beta_and_longer_timeout() -> None:
    llm, create, options = _mcp_client(
        [_text('{"signal":"neutral","confidence":50,"reasoning":"x"}')]
    )

    await llm.generate(system="s", prompt="p", schema=LLMSignal, mcp_servers=[FACTSET])

    kwargs = create.await_args.kwargs
    assert kwargs["betas"] == [MCP_BETA]
    assert kwargs["tools"] == [{"type": "mcp_toolset", "mcp_server_name": "factset"}]
    assert kwargs["mcp_servers"] == [
        {
            "type": "url",
            "url": "https://mcp.factset.com/content/v1",
            "name": "factset",
            "authorization_token": "tok",
        }
    ]
    assert "output_config" in kwargs  # still a structured reply
    assert "extra_body" not in kwargs
    assert options == [{"timeout": 120.0}]


@pytest.mark.unit
async def test_mcp_reply_is_the_final_text_after_tool_blocks() -> None:
    llm, _, _ = _mcp_client(
        [
            _text("Let me look up the fundamentals."),
            SimpleNamespace(type="mcp_tool_use", name="get_fundamentals", server_name="factset"),
            SimpleNamespace(type="mcp_tool_result", content=[]),
            _text('{"signal":"bearish","confidence":70,"reasoning":"margins fell"}'),
        ]
    )
    result = await llm.generate(system="s", prompt="p", schema=LLMSignal, mcp_servers=[FACTSET])
    assert result == LLMSignal(signal="bearish", confidence=70, reasoning="margins fell")


@pytest.mark.unit
async def test_invalid_mcp_servers_are_rejected_before_calling_claude() -> None:
    llm, create, _ = _mcp_client([])
    with pytest.raises(ValueError, match="Duplicate"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal, mcp_servers=[FACTSET, FACTSET])
    insecure = McpServer(name="x", url="http://insecure")
    with pytest.raises(ValueError, match="https"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal, mcp_servers=[insecure])
    create.assert_not_awaited()


@pytest.mark.unit
def test_server_param_and_toolset_allowlist() -> None:
    kensho = McpServer(name="sp", url="https://kfinance.kensho.com/integrations/mcp")
    assert kensho.to_server_param() == {
        "type": "url",
        "url": "https://kfinance.kensho.com/integrations/mcp",
        "name": "sp",
    }
    morningstar = McpServer(
        name="ms", url="https://mcp.morningstar.com/mcp", allowed_tools=("fair_value",)
    )
    assert morningstar.to_toolset_param() == {
        "type": "mcp_toolset",
        "mcp_server_name": "ms",
        "default_config": {"enabled": False},
        "configs": {"fair_value": {"enabled": True}},
    }


class _Recorder:
    def __init__(self) -> None:
        self.calls: list = []

    async def record(self, call) -> None:
        self.calls.append(call)


def _usage_message(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    message = _message(text, stop_reason)
    message.usage = SimpleNamespace(
        input_tokens=900,
        output_tokens=60,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=0,
    )
    message._request_id = "req_123"
    return message


def _recording_client(reply: object, **kwargs) -> tuple[LLMClient, _Recorder]:
    recorder = _Recorder()
    sdk = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()), close=AsyncMock())
    if isinstance(reply, Exception):
        sdk.messages.create.side_effect = reply
    else:
        sdk.messages.create.return_value = reply
    return LLMClient(sdk, "claude-haiku-4-5", recorder=recorder, **kwargs), recorder


@pytest.mark.unit
async def test_successful_call_is_recorded_with_usage_cost_and_context() -> None:
    from app.core.context import bind_run

    llm, recorder = _recording_client(
        _usage_message('{"signal":"bullish","confidence":70,"reasoning":"r"}')
    )
    with bind_run(pipeline_run_id="p1", run_id="r1", agent="moat", symbol="AAPL") as usage:
        await llm.generate(system="sys", prompt="user", schema=LLMSignal, prompt_name="moat")

    (call,) = recorder.calls
    assert (call.status, call.model, call.prompt_name) == ("ok", "claude-haiku-4-5", "moat")
    assert (call.run_id, call.pipeline_run_id, call.agent, call.symbol) == (
        "r1",
        "p1",
        "moat",
        "AAPL",
    )
    assert (call.usage.input_tokens, call.usage.output_tokens) == (900, 60)
    assert call.usage.cache_read_tokens == 100
    assert call.cost_usd == pytest.approx((900 * 1.0 + 60 * 5.0 + 100 * 0.1) / 1e6)
    assert call.request_id == "req_123"
    assert (call.system_prompt, call.prompt) == ("sys", "user")
    assert call.response.startswith('{"signal"')
    assert call.latency_ms >= 0
    # The agent run's totals see the call (cache reads count as input)
    assert (usage.llm_calls, usage.input_tokens, usage.output_tokens) == (1, 1000, 60)
    assert usage.cost_usd == pytest.approx(call.cost_usd)


@pytest.mark.unit
async def test_failed_calls_are_recorded_as_errors() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    status = anthropic.APIStatusError(
        "overloaded", response=httpx2.Response(529, request=request), body=None
    )
    for reply in (
        status,
        anthropic.APIConnectionError(request=request),
        _usage_message('{"signal":', stop_reason="max_tokens"),
        _usage_message('{"signal":"maybe","confidence":1,"reasoning":"r"}'),
    ):
        llm, recorder = _recording_client(reply)
        with pytest.raises(LLMError):
            await llm.generate(system="s", prompt="p", schema=LLMSignal)
        (call,) = recorder.calls
        assert call.status == "error"
        assert call.error


@pytest.mark.unit
async def test_tokens_spent_on_an_invalid_reply_are_still_counted() -> None:
    from app.core.context import bind_run

    llm, recorder = _recording_client(_usage_message("not json"))
    with bind_run() as usage, pytest.raises(LLMError):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)
    assert recorder.calls[0].usage.input_tokens == 900
    assert usage.input_tokens == 1000


@pytest.mark.unit
async def test_content_capture_can_be_turned_off() -> None:
    llm, recorder = _recording_client(
        _usage_message('{"signal":"neutral","confidence":1,"reasoning":"r"}'),
        capture_content=False,
    )
    await llm.generate(system="secret system", prompt="p", schema=LLMSignal)
    (call,) = recorder.calls
    assert (call.system_prompt, call.prompt, call.response) == (None, None, None)
    assert call.prompt_version  # the version is kept even without the text


@pytest.mark.unit
async def test_unpriced_model_marks_run_cost_incomplete() -> None:
    from app.core.context import bind_run

    llm, recorder = _recording_client(
        _usage_message('{"signal":"neutral","confidence":1,"reasoning":"r"}')
    )
    with bind_run() as usage:
        await llm.generate(system="s", prompt="p", schema=LLMSignal, model="unknown-model")
    assert recorder.calls[0].cost_usd is None
    assert usage.cost_complete is False


@pytest.mark.unit
async def test_calls_are_logged_with_token_counts(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="app.llm.tracking")
    llm, _ = _recording_client(
        _usage_message('{"signal":"neutral","confidence":1,"reasoning":"r"}')
    )
    await llm.generate(system="s", prompt="p", schema=LLMSignal, prompt_name="moat")
    (record,) = (r for r in caplog.records if r.message == "LLM call completed")
    assert (record.input_tokens, record.output_tokens, record.prompt_name) == (900, 60, "moat")
