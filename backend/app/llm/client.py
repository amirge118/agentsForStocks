"""
LLMClient — the only place that calls the Anthropic API.

Replies are constrained with structured outputs (output_config.format, JSON
schema derived from the Pydantic model) and then validated by Pydantic, so
agents receive typed objects instead of scraping JSON out of free text.
Failures raise LLMError; the agent runner decides how to degrade.
"""

import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.llm.schema import output_schema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Claude could not produce a valid structured reply."""


class LLMClient:
    def __init__(self, client: anthropic.AsyncAnthropic, default_model: str) -> None:
        self._client = client
        self.default_model = default_model

    async def generate(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> T:
        chosen = model or self.default_model
        try:
            message = await self._client.messages.create(
                model=chosen,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                # Pinned SDK predates the typed parameter, so send it as raw body
                extra_body={
                    "output_config": {
                        "format": {"type": "json_schema", "schema": output_schema(schema)}
                    }
                },
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(f"{chosen} returned HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"{chosen} unreachable: {exc}") from exc

        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMError(f"{chosen} stopped with {message.stop_reason}")

        text = next((block.text for block in message.content if block.type == "text"), "")
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("Claude reply failed schema validation: %.200s", text)
            raise LLMError(f"{chosen} reply did not match {schema.__name__}") from exc

    async def aclose(self) -> None:
        await self._client.close()
