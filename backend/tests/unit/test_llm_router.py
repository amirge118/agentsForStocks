import pytest

from app.container import build_llm_router
from app.core.config import Settings
from app.llm.client import LLMClient
from app.llm.errors import LLMError
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.recording import NullRecorder
from app.llm.router import LLMRouter
from app.schemas.signals import LLMSignal
from tests.factories import FakeLLM


@pytest.mark.unit
async def test_routes_by_provider_and_falls_back_to_the_default() -> None:
    claude, cheap = FakeLLM(), FakeLLM()
    cheap.default_model = "cheap-model"  # providers expose their default model as a string
    router = LLMRouter({"anthropic": claude, "alt": cheap}, default_provider="anthropic")
    await router.generate(system="s", prompt="p", schema=LLMSignal)
    await router.generate(provider="alt", system="s", prompt="p", schema=LLMSignal)
    assert (len(claude.calls), len(cheap.calls)) == (1, 1)
    assert router.configured("alt") and router.default_model("alt") == "cheap-model"


@pytest.mark.unit
async def test_an_unconfigured_provider_is_an_llm_error() -> None:
    router = LLMRouter({"anthropic": FakeLLM()})
    with pytest.raises(LLMError, match="not configured"):
        await router.generate(provider="alt", system="s", prompt="p", schema=LLMSignal)
    assert router.default_model("alt") is None
    await router.aclose()


@pytest.mark.unit
async def test_container_adds_the_alt_provider_only_when_configured() -> None:
    plain = build_llm_router(Settings(), NullRecorder())
    assert not plain.configured("alt")
    assert isinstance(plain._providers["anthropic"], LLMClient)

    alt = build_llm_router(
        Settings(
            llm_provider="alt",
            llm_alt_base_url="http://localhost:11434/v1",
            llm_alt_model="qwen3:8b",
            llm_alt_input_price=0.0,
        ),
        NullRecorder(),
    )
    assert isinstance(alt._providers["alt"], OpenAICompatibleClient)
    assert (alt.default_provider, alt.default_model()) == ("alt", "qwen3:8b")
    await plain.aclose()
    await alt.aclose()


@pytest.mark.unit
async def test_free_providers_join_when_their_key_is_set_and_form_the_chain() -> None:
    router = build_llm_router(
        Settings(
            gemini_api_key="g",
            cerebras_api_key="c",
            llm_provider="chain",
            llm_providers='{"cerebras": {"rpd": 77}}',
        ),
        NullRecorder(),
    )
    assert [p.name for p in router.providers()] == ["anthropic", "gemini", "cerebras"]
    gemini = router.provider("gemini")
    assert isinstance(gemini, OpenAICompatibleClient) and gemini.name == "gemini"
    assert gemini.quota is not None and gemini.quota.limits.rpm == 10
    assert router.provider("cerebras").quota.limits.rpd == 77
    # No ANTHROPIC_API_KEY: Claude stays routable but is left out of the chain
    assert router.chain_order() == ["gemini", "cerebras"]
    assert router.default_model() == "gemini-3.5-flash-lite"
    await router.aclose()


@pytest.mark.unit
async def test_claude_is_the_chains_last_step_when_its_key_is_set(caplog) -> None:
    router = build_llm_router(
        Settings(groq_api_key="q", anthropic_api_key="a" * 40), NullRecorder()
    )
    assert router.chain_order() == ["groq", "anthropic"]
    assert router.default_model("chain") == "openai/gpt-oss-120b"
    await router.aclose()

    with caplog.at_level("WARNING"):
        unknown = build_llm_router(Settings(llm_provider="mistral"), NullRecorder())
    assert "LLM_PROVIDER is not configured" in caplog.text
    await unknown.aclose()
