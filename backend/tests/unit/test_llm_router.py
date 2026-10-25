import pytest

from app.container import build_llm_router
from app.core.config import Settings
from app.llm.client import LLMClient, LLMError
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
