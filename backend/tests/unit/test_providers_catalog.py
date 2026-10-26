import json

import pytest

from app.llm.providers_catalog import BUILTIN, configured, load_specs


@pytest.mark.unit
def test_builtin_free_providers() -> None:
    assert set(BUILTIN) == {"gemini", "groq", "cerebras"}
    assert BUILTIN["gemini"].limits.reset_tz == "America/Los_Angeles"
    for spec in BUILTIN.values():
        assert spec.base_url.startswith("https://") and spec.key_env.endswith("_API_KEY")
        assert (spec.input_price, spec.output_price) == (0.0, 0.0)


@pytest.mark.unit
def test_overrides_change_fields_and_limits_and_keep_the_rest(tmp_path) -> None:
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"groq": {"model": "qwen/qwen3-32b", "rpd": 500}}))
    specs = load_specs('{"groq": {"rpd": 900}, "cerebras": {"enabled": false}}', str(path))
    groq = specs["groq"]
    assert groq.model == "qwen/qwen3-32b"  # from the file
    assert groq.limits.rpd == 900  # inline wins over the file
    assert groq.limits.tpm == BUILTIN["groq"].limits.tpm
    assert groq.extra_body == {"reasoning_effort": "low"}
    assert not specs["cerebras"].enabled


@pytest.mark.unit
def test_a_new_provider_needs_url_model_and_key_variable() -> None:
    spec = load_specs(
        '{"openrouter": {"base_url": "https://openrouter.ai/api/v1", '
        '"model": "x/y:free", "key_env": "OPENROUTER_API_KEY", "rpd": 50}}'
    )["openrouter"]
    assert (spec.model, spec.limits.rpd, spec.structured_mode) == ("x/y:free", 50, "json_schema")
    with pytest.raises(ValueError, match="needs"):
        load_specs('{"local": {"model": "qwen3:8b"}}')


@pytest.mark.unit
def test_unknown_fields_and_keys_in_json_are_rejected() -> None:
    with pytest.raises(ValueError, match="never here"):
        load_specs('{"groq": {"api_key": "gsk_secret"}}')


@pytest.mark.unit
def test_only_enabled_providers_with_a_key_are_configured() -> None:
    specs = load_specs('{"cerebras": {"enabled": false}}')
    keys = {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "", "CEREBRAS_API_KEY": "c"}
    assert [(s.name, k) for s, k in configured(specs, keys)] == [("gemini", "g")]


@pytest.mark.unit
def test_the_alt_provider_is_a_spec_too_and_needs_no_key() -> None:
    from app.llm.providers_catalog import alt_spec

    spec = alt_spec(
        "http://localhost:11434/v1",
        "qwen3:8b",
        input_price=0.0,
        output_price=0.0,
        timeout_seconds=60,
    )
    assert not spec.limits.bounded  # no free-tier quota: a 429 is retried as before
    assert [s.name for s, _ in configured({"alt": spec}, {})] == ["alt"]  # Ollama takes no key
    assert spec.price.cache_read == 0.0
    assert BUILTIN["gemini"].limits.bounded
