"""
Free and near-free LLM providers, ready to use: set the API key and they join
the router (and the fallback chain, app/llm/chain.py).

    GEMINI_API_KEY    Google AI Studio   https://aistudio.google.com/apikey
    GROQ_API_KEY      Groq               https://console.groq.com/keys
    CEREBRAS_API_KEY  Cerebras           https://cloud.cerebras.ai

The quotas below are conservative readings of each free tier (October 2026);
the providers change them often, so the preflight checks the model ids against
each service and you can override anything without code:

    LLM_PROVIDERS='{"groq": {"model": "qwen/qwen3-32b", "rpd": 900}}'
    LLM_PROVIDERS_FILE=config/llm_providers.json

An override can also add a provider (it then needs base_url, model and key_env).
API keys never go in these JSON settings — only the name of the variable that
holds the key.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from app.llm.openai_compat import StructuredMode
from app.llm.pricing import Price
from app.llm.provider import ALT
from app.llm.quota import QuotaLimits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    model: str
    key_env: str
    structured_mode: StructuredMode = "json_schema"
    limits: QuotaLimits = QuotaLimits()
    extra_body: dict[str, Any] = field(default_factory=dict)
    reasoning_tokens: int = 0
    # USD per million tokens (0 = free tier)
    input_price: float = 0.0
    output_price: float = 0.0
    timeout_seconds: float = 60.0
    enabled: bool = True
    # False for a local server (Ollama) that takes no key
    key_required: bool = True

    @property
    def price(self) -> Price:
        return Price.flat(self.input_price, self.output_price)


def alt_spec(
    base_url: str, model: str, *, input_price: float, output_price: float, timeout_seconds: float
) -> ProviderSpec:
    """The LLM_ALT_* provider: any OpenAI-compatible API, no free-tier limits, key optional."""
    return ProviderSpec(
        name=ALT,
        base_url=base_url,
        model=model,
        key_env="LLM_ALT_API_KEY",
        input_price=input_price,
        output_price=output_price,
        timeout_seconds=timeout_seconds,
        key_required=False,
    )


BUILTIN: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-3.5-flash-lite",
        key_env="GEMINI_API_KEY",
        # Daily quota resets at midnight Pacific
        limits=QuotaLimits(rpm=10, tpm=250_000, rpd=1_000, reset_tz="America/Los_Angeles"),
    ),
    "groq": ProviderSpec(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        key_env="GROQ_API_KEY",
        # Strict JSON-schema support varies by model on Groq; JSON mode works on all
        structured_mode="json_object",
        limits=QuotaLimits(rpm=30, tpm=6_000, rpd=1_000, tpd=200_000),
        extra_body={"reasoning_effort": "low"},
        reasoning_tokens=1_024,
    ),
    "cerebras": ProviderSpec(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        model="gpt-oss-120b",
        key_env="CEREBRAS_API_KEY",
        structured_mode="json_object",
        limits=QuotaLimits(rpm=30, tpm=60_000, tpd=1_000_000),
        extra_body={"reasoning_effort": "low"},
        reasoning_tokens=1_024,
    ),
}

_LIMIT_FIELDS = {f.name for f in fields(QuotaLimits)}
_SPEC_FIELDS = {f.name for f in fields(ProviderSpec)} - {"name", "limits"}


def load_specs(overrides_json: str = "", overrides_file: str = "") -> dict[str, ProviderSpec]:
    """The built-in providers with the configured overrides applied (file first, then inline)."""
    overrides: dict[str, dict[str, Any]] = {}
    sources = [Path(overrides_file).read_text(encoding="utf-8")] if overrides_file else []
    for source in [*sources, overrides_json]:
        for name, fields_ in (json.loads(source) if source else {}).items():
            overrides[name] = {**overrides.get(name, {}), **fields_}  # merge, field by field
    specs = dict(BUILTIN)
    for name, override in overrides.items():
        specs[name] = _apply(specs.get(name), name, override)
    return specs


def _apply(base: ProviderSpec | None, name: str, override: dict[str, Any]) -> ProviderSpec:
    unknown = set(override) - _SPEC_FIELDS - _LIMIT_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown fields for LLM provider {name!r}: {sorted(unknown)} "
            "(API keys go in the variable named by key_env, never here)"
        )
    spec_values = {k: v for k, v in override.items() if k in _SPEC_FIELDS}
    limit_values = {k: v for k, v in override.items() if k in _LIMIT_FIELDS}
    if base is None:
        missing = {"base_url", "model", "key_env"} - set(spec_values)
        if missing:
            raise ValueError(f"New LLM provider {name!r} needs {sorted(missing)}")
        return ProviderSpec(name=name, limits=QuotaLimits(**limit_values), **spec_values)
    return replace(base, limits=replace(base.limits, **limit_values), **spec_values)


def configured(
    specs: Mapping[str, ProviderSpec], keys: Mapping[str, str]
) -> list[tuple[ProviderSpec, str]]:
    """Enabled providers whose API key is set, with that key."""
    out = []
    for spec in specs.values():
        key = keys.get(spec.key_env, "")
        if spec.enabled and (key or not spec.key_required):
            out.append((spec, key))
    return out
