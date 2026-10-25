"""System prompts live in app/llm/prompts/<name>.md so they can be edited without touching code."""

from functools import cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts"


@cache
def load_prompt(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
