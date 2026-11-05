"""
Reuse a model's reply when nothing that shaped it changed. The prompt holds what an
agent actually judges, so an agent whose data is the same as last time (a 10-K, annual
statements) makes no call, whatever the date, while one that shows today's price still
does. A reply expires after LLM_REUSE_MAX_DAYS, and `--force` always asks the model.
Only validated replies are stored, so a fallback is never reused. A failure here never
stops a judgement: it just means one more model call.
"""

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import utcnow
from app.models.llm_reply import LLMReply

logger = logging.getLogger(__name__)


def reply_key(**parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class StoredReplies:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], max_age_days: int):
        self._session_factory = session_factory
        self._max_age = timedelta(days=max_age_days)

    async def get(self, key: str) -> str | None:
        try:
            async with self._session_factory() as session:
                return await session.scalar(
                    select(LLMReply.reply).where(
                        LLMReply.key == key, LLMReply.created_at >= utcnow() - self._max_age
                    )
                )
        except Exception as exc:
            logger.warning("Reused replies unavailable", extra={"error": str(exc)})
            return None

    async def put(self, key: str, prompt_name: str, reply: str) -> None:
        try:
            async with self._session_factory() as session:
                await session.merge(
                    LLMReply(key=key, prompt_name=prompt_name, reply=reply, created_at=utcnow())
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Reply not stored for reuse", extra={"error": str(exc)})

    async def prune(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(LLMReply).where(LLMReply.created_at < utcnow() - self._max_age)
            )
            await session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
