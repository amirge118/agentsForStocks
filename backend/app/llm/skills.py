"""
Skills — reusable pieces of analysis guidance (app/llm/skills/<name>.md) that a
profile adds to an agent's system prompt, e.g. how to calibrate confidence or
what counts as evidence of a moat. Swapping or adding a skill is a profile
change, so its effect on accuracy and tokens can be measured with the evals
before it becomes a default.

A skill file starts with a small front-matter block:

    ---
    name: confidence_calibration
    version: 1
    description: What 30 / 60 / 90 % confidence means
    ---
    <guidance text>

Skills are appended after the base prompt in the order the profile lists them,
so the system prompt stays a stable prefix (good for prompt caching) and its
prompt_version changes whenever a skill's text does.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.llm.prompt_loader import load_prompt

_SKILL_DIR = Path(__file__).parent / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    description: str
    body: str


@cache
def load_skill(name: str) -> Skill:
    path = _SKILL_DIR / f"{name}.md"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in _SKILL_DIR.glob("*.md")))
        raise ValueError(f"Unknown skill {name!r} (available: {available})")
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    return Skill(
        name=meta.get("name", name),
        version=meta.get("version", "1"),
        description=meta.get("description", ""),
        body=body.strip(),
    )


def available_skills() -> list[Skill]:
    return [load_skill(p.stem) for p in sorted(_SKILL_DIR.glob("*.md"))]


def compose_system(prompt: str, skills: tuple[str, ...]) -> str:
    """The base system prompt followed by each skill's guidance."""
    parts = [load_prompt(prompt)]
    for name in skills:
        skill = load_skill(name)
        parts.append(f"## {skill.name.replace('_', ' ').capitalize()}\n{skill.body}")
    return "\n\n".join(parts)


def prompt_label(prompt: str, skills: tuple[str, ...]) -> str:
    """How the call is labelled in the ledger: the prompt plus its skills."""
    return prompt if not skills else f"{prompt}+{'+'.join(skills)}"


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, header, body = text.split("---", 2)
    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body
