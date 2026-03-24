"""
LLM service — wrapper around the Anthropic SDK for agent use.
Adapted from virattt/ai-hedge-fund utils/llm.py.

All agents call call_claude() instead of instantiating the client directly.
Handles: retry with backoff, JSON extraction, fallback responses.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import settings
from app.services.external_api_base import with_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None

# Default model — cheap + fast for most agent analysis
DEFAULT_MODEL = "claude-haiku-4-5"
# Use Sonnet for complex multi-step reasoning
REASONING_MODEL = "claude-sonnet-4-6"


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


async def call_claude(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    response_model: type[T] | None = None,
) -> T | dict[str, Any]:
    """
    Call Claude with retry. Returns:
    - A parsed Pydantic model if response_model is provided
    - A dict if response_model is None (raw JSON from Claude)

    Claude is instructed to return valid JSON. If parsing fails, falls back
    to a default response (neutral signal, 0 confidence).
    """
    def _call() -> str:
        message = _get_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt + "\n\nYou MUST return valid JSON only. No markdown, no explanation outside JSON.",
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text.strip()

    try:
        raw = await with_retry(_call, label=f"claude({model})", timeout=30.0)
        parsed = _extract_json(raw)

        if response_model is not None:
            return response_model(**parsed)
        return parsed

    except Exception as exc:
        logger.warning("Claude call failed, using fallback: %s", exc)
        fallback = _default_response(response_model)
        if response_model is not None:
            return response_model(**fallback)
        return fallback


def _extract_json(text: str) -> dict[str, Any]:
    """
    Extract JSON from Claude's response.
    Handles markdown code fences (```json ... ```) and bare JSON.
    """
    # Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Could not extract JSON from Claude response: %.200s", text)
    return {}


def _default_response(model: type[BaseModel] | None) -> dict[str, Any]:
    """Generate a safe fallback dict when Claude fails."""
    defaults: dict[str, Any] = {
        "signal": "neutral",
        "confidence": 0.0,
        "reasoning": "Analysis unavailable — LLM call failed.",
    }
    if model is None:
        return defaults

    # Fill in any fields the model expects that aren't in defaults
    for field_name, field_info in model.model_fields.items():
        if field_name not in defaults:
            annotation = field_info.annotation
            if annotation is str or (hasattr(annotation, "__origin__") is False and annotation is not None):
                defaults[field_name] = "" if annotation is str else 0.0

    return defaults
