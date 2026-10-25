"""
AgentProfile — how an agent (or one of its prompts) talks to the model: which
provider and model, which skills are added to the system prompt, the output
budget, and whether to call the model at all.

Each agent declares a default with @register_agent(profile=...). Overrides come
from configuration, so a model, provider or skill can be swapped for one agent
— e.g. for an eval or a cost experiment — without touching code:

    AGENT_PROFILES='{"*": {"provider": "alt"}, "moat": {"skills": ["moat_evidence"]}}'
    AGENT_PROFILES_FILE=config/agent_profiles.json

Keys are prompt names: the agent's name for its main judgement, or the name of
a secondary prompt (e.g. "news_sentiment"). "*" applies to every prompt.
Precedence: agent default < "*" < the prompt's own entry.
"""

import json
import logging
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from app.llm.skills import load_skill

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentProfile:
    # None = the configured default provider (LLM_PROVIDER)
    provider: str | None = None
    # None = the call's own model hint (e.g. the reasoning model), else the provider default
    model: str | None = None
    skills: tuple[str, ...] = ()
    # None = the call's own budget
    max_tokens: int | None = None
    # False = skip the model and use the agent's rule-based signal (saves the whole call)
    use_llm: bool = True
    # Prompt file in app/llm/prompts/ (None = the prompt name) — for prompt variants
    prompt: str | None = None

    def merged(self, override: dict[str, Any]) -> "AgentProfile":
        known = {f.name for f in fields(self)}
        unknown = set(override) - known
        if unknown:
            raise ValueError(f"Unknown agent profile fields: {sorted(unknown)}")
        values = dict(override)
        if "skills" in values:
            values["skills"] = tuple(values["skills"])
        return replace(self, **values)


class ProfileBook:
    """Resolves the effective profile of a prompt from defaults plus overrides."""

    def __init__(self, overrides: dict[str, dict[str, Any]] | None = None) -> None:
        self._overrides = overrides or {}
        for key, override in self._overrides.items():  # fail fast on typos and unknown skills
            for skill in AgentProfile().merged(override).skills:
                load_skill(skill)
            logger.info("Agent profile override", extra={"prompt_key": key, "override": override})

    @classmethod
    def from_config(cls, inline: str = "", path: str = "") -> "ProfileBook":
        overrides: dict[str, dict[str, Any]] = {}
        if path:
            overrides.update(json.loads(Path(path).read_text(encoding="utf-8")))
        if inline:
            overrides.update(json.loads(inline))
        return cls(overrides)

    def resolve(self, key: str, default: AgentProfile) -> AgentProfile:
        profile = default
        for layer in ("*", key):
            if layer in self._overrides:
                profile = profile.merged(self._overrides[layer])
        return profile

    @property
    def overrides(self) -> dict[str, dict[str, Any]]:
        return dict(self._overrides)
