import json

import httpx
import pytest

from app.core.context import bind_run
from app.llm.errors import LLMError, QuotaExhaustedError
from app.llm.mcp import McpServer
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.pricing import Price
from app.llm.quota import ProviderQuota, QuotaLimits
from app.providers.retry import RetryPolicy
from app.schemas.signals import LLMSignal

FAST = RetryPolicy(max_attempts=3, timeout_seconds=5, base_backoff_seconds=0)
REPLY = '{"signal":"bullish","confidence":64,"reasoning":"Cheap and growing"}'


class _Recorder:
    def __init__(self) -> None:
        self.calls: list = []

    async def record(self, call) -> None:
        self.calls.append(call)


def _completion(content: str = REPLY, finish: str = "stop", cached: int = 0) -> dict:
    return {
        "id": "chatcmpl-1",
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


def _client(handler, recorder=None) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://llm.example.com/v1/",
        api_key="sk-test",
        default_model="flash-lite",
        recorder=recorder,
        prices={"flash-lite": Price(input=0.1, output=0.4, cache_read=0.025, cache_write=0.1)},
        transport=httpx.MockTransport(handler),
        retry_policy=FAST,
    )


@pytest.mark.unit
async def test_structured_reply_usage_cost_and_ledger() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completion(cached=200))

    recorder = _Recorder()
    llm = _client(handler, recorder)
    with bind_run(agent="moat", symbol="AAPL") as usage:
        result = await llm.generate(
            system="sys", prompt="user", schema=LLMSignal, prompt_name="moat"
        )

    assert result == LLMSignal(signal="bullish", confidence=64, reasoning="Cheap and growing")
    request = seen[0]
    assert str(request.url) == "https://llm.example.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "flash-lite"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["required"] == ["signal", "confidence", "reasoning"]

    (call,) = recorder.calls
    assert (call.status, call.model, call.agent, call.request_id) == (
        "ok",
        "flash-lite",
        "moat",
        "chatcmpl-1",
    )
    assert (call.usage.input_tokens, call.usage.cache_read_tokens, call.usage.output_tokens) == (
        1000,
        200,
        50,
    )
    assert call.cost_usd == pytest.approx((1000 * 0.1 + 200 * 0.025 + 50 * 0.4) / 1e6)
    assert (usage.llm_calls, usage.input_tokens) == (1, 1200)


@pytest.mark.unit
async def test_json_in_code_fences_is_accepted() -> None:
    fenced = f"```json\n{REPLY}\n```"
    llm = _client(lambda r: httpx.Response(200, json=_completion(content=fenced)))
    assert (await llm.generate(system="s", prompt="p", schema=LLMSignal)).signal == "bullish"


@pytest.mark.unit
async def test_transient_errors_are_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=_completion())

    assert (
        await _client(handler).generate(system="s", prompt="p", schema=LLMSignal)
    ).confidence == 64
    assert attempts["n"] == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    ("response", "attempts_expected"),
    [
        (httpx.Response(503), 3),  # retried, then given up
        (httpx.Response(401, json={"error": "bad key"}), 1),  # not retried
        (httpx.Response(200, json=_completion(finish="length")), 1),
        (httpx.Response(200, json=_completion(content='{"signal":"maybe"}')), 1),
        (httpx.Response(200, text="<html>proxy error</html>"), 1),
    ],
)
async def test_failures_raise_llm_error_and_are_recorded(response, attempts_expected) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return response

    recorder = _Recorder()
    with pytest.raises(LLMError):
        await _client(handler, recorder).generate(system="s", prompt="p", schema=LLMSignal)
    assert attempts["n"] == attempts_expected
    assert recorder.calls[0].status == "error"


@pytest.mark.unit
async def test_mcp_servers_are_rejected_and_client_closes() -> None:
    llm = _client(lambda r: httpx.Response(200, json=_completion()))
    server = McpServer(name="factset", url="https://mcp.factset.com/x", authorization_token="t")
    with pytest.raises(ValueError, match="Anthropic"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal, mcp_servers=[server])
    await llm.aclose()


def _free(handler, *, quota=None, mode="json_schema", **kw) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://free.example.com/v1",
        api_key="k",
        default_model="free-model",
        name="groq",
        structured_mode=mode,
        quota=quota,
        transport=httpx.MockTransport(handler),
        retry_policy=FAST,
        **kw,
    )


@pytest.mark.unit
async def test_json_object_mode_extra_body_and_reasoning_budget() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_completion())

    recorder = _Recorder()
    llm = _free(
        handler,
        mode="json_object",
        extra_body={"reasoning_effort": "low"},
        reasoning_tokens=1024,
        recorder=recorder,
    )
    await llm.generate(system="sys", prompt="user", schema=LLMSignal, max_tokens=512)
    body = seen[0]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low" and body["max_tokens"] == 1536
    system = body["messages"][0]["content"]
    assert (
        system.startswith("sys\n\n") and '"required":["signal","confidence","reasoning"]' in system
    )
    (call,) = recorder.calls
    # The ledger keeps the agent's own system prompt: same prompt version in either mode
    assert (call.provider, call.system_prompt) == ("groq", "sys")


@pytest.mark.unit
async def test_a_429_on_a_free_tier_cools_down_instead_of_retrying() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"retry-after": "20"})

    quota = ProviderQuota("groq", QuotaLimits(rpm=30))
    recorder = _Recorder()
    llm = _free(handler, quota=quota, recorder=recorder)
    with pytest.raises(QuotaExhaustedError, match="rate limited"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)
    assert attempts == 1 and recorder.calls[0].status == "error"
    # Cooling down for 20 s: nothing is sent and nothing is recorded
    with pytest.raises(QuotaExhaustedError, match="no room"):
        await llm.generate(system="s", prompt="p", schema=LLMSignal)
    assert attempts == 1 and len(recorder.calls) == 1


@pytest.mark.unit
async def test_quota_is_settled_with_real_usage() -> None:
    quota = ProviderQuota("groq", QuotaLimits(tpd=100_000))
    llm = _free(lambda r: httpx.Response(200, json=_completion()), quota=quota)
    await llm.generate(system="s", prompt="p", schema=LLMSignal, max_tokens=4000)
    assert (quota.day_requests, quota.day_tokens) == (1, 1250)  # 1200 in + 50 out


@pytest.mark.unit
async def test_list_models_strips_the_gemini_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200, json={"data": [{"id": "models/gemini-3.5-flash-lite"}, {"id": "gpt-oss-120b"}, {}]}
        )

    assert await _free(handler).list_models() == ["gemini-3.5-flash-lite", "gpt-oss-120b"]
