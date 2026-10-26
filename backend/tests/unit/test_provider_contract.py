"""Every model client follows the provider contract the router, chain, API and preflight rely on."""

import anthropic
import pytest

from app.llm.client import LLMClient
from app.llm.errors import LLMError, QuotaExhaustedError
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.provider import LLMProvider
from app.llm.quota import ProviderQuota, QuotaLimits

CONTRACT = ("name", "default_model", "structured_mode", "quota", "generate", "price", "aclose")
# The list above is the Protocol: fields are annotations, methods are attributes
assert set(CONTRACT) <= set(LLMProvider.__annotations__) | set(vars(LLMProvider))


def _clients() -> list[object]:
    return [
        LLMClient(anthropic.AsyncAnthropic(api_key="x"), default_model="claude-haiku-5-5"),
        OpenAICompatibleClient(
            base_url="https://free.example.com/v1",
            api_key="k",
            default_model="free-model",
            name="gemini",
            quota=ProviderQuota("gemini", QuotaLimits(rpd=10)),
        ),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("client", _clients(), ids=["claude", "openai_compatible"])
def test_every_client_offers_the_whole_contract(client: object) -> None:
    missing = [attr for attr in CONTRACT if not hasattr(client, attr)]
    assert missing == []


@pytest.mark.unit
def test_contract_values() -> None:
    claude, free = _clients()
    assert (claude.name, claude.structured_mode, claude.quota) == ("anthropic", "native", None)
    assert claude.price("claude-haiku-5-5") is not None and claude.price("nope") is None
    assert (free.name, free.structured_mode) == ("gemini", "json_schema")
    assert free.quota is not None and free.price("free-model") is None  # no price configured


@pytest.mark.unit
def test_a_quota_miss_is_an_llm_error() -> None:
    # Agents and the chain catch LLMError; a free tier with no room must be one
    assert issubclass(QuotaExhaustedError, LLMError)
