"""LLMCallRepository — per-call LLM ledger: listing, usage aggregates and retention."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_call import LLMCall

GroupBy = Literal["agent", "model", "day", "prompt_version"]


@dataclass(frozen=True)
class UsageRow:
    key: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    avg_latency_ms: float


class LLMCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, call: LLMCall) -> None:
        self._session.add(call)

    async def usage(self, *, since: datetime, group_by: GroupBy) -> list[UsageRow]:
        """Token and cost totals per group since `since`, most expensive first."""
        key = {
            "agent": func.coalesce(LLMCall.agent, "(none)"),
            "model": LLMCall.model,
            "day": func.date(LLMCall.created_at),
            "prompt_version": func.coalesce(LLMCall.prompt_name, "(none)")
            + "@"
            + LLMCall.prompt_version,
        }[group_by].label("key")
        cost = func.coalesce(func.sum(LLMCall.cost_usd), 0.0)
        stmt = (
            select(
                key,
                func.count().label("calls"),
                func.sum(case((LLMCall.status == "error", 1), else_=0)).label("errors"),
                func.sum(LLMCall.input_tokens).label("input_tokens"),
                func.sum(LLMCall.output_tokens).label("output_tokens"),
                func.sum(LLMCall.cache_read_tokens).label("cache_read_tokens"),
                func.sum(LLMCall.cache_write_tokens).label("cache_write_tokens"),
                cost.label("cost_usd"),
                func.avg(LLMCall.latency_ms).label("avg_latency_ms"),
            )
            .where(LLMCall.created_at >= since)
            .group_by(key)
            .order_by(cost.desc(), key)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            UsageRow(
                key=str(r.key),
                calls=int(r.calls),
                errors=int(r.errors or 0),
                input_tokens=int(r.input_tokens or 0),
                output_tokens=int(r.output_tokens or 0),
                cache_read_tokens=int(r.cache_read_tokens or 0),
                cache_write_tokens=int(r.cache_write_tokens or 0),
                cost_usd=float(r.cost_usd or 0.0),
                avg_latency_ms=float(r.avg_latency_ms or 0.0),
            )
            for r in rows
        ]

    async def provider_totals(self, provider: str, since: datetime) -> tuple[int, int]:
        """Requests and tokens (input + output, cache included) sent to a provider since `since`."""
        tokens = (
            LLMCall.input_tokens
            + LLMCall.output_tokens
            + LLMCall.cache_read_tokens
            + LLMCall.cache_write_tokens
        )
        stmt = select(func.count(), func.coalesce(func.sum(tokens), 0)).where(
            LLMCall.provider == provider, LLMCall.created_at >= since
        )
        requests, used = (await self._session.execute(stmt)).one()
        return int(requests), int(used)

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self._session.execute(delete(LLMCall).where(LLMCall.created_at < cutoff))
        return int(getattr(result, "rowcount", 0) or 0)

    # Defined last: inside the class body the name `list` would shadow the builtin
    async def list(
        self,
        *,
        run_id: str | None = None,
        pipeline_run_id: str | None = None,
        agent: str | None = None,
        limit: int = 100,
    ) -> list[LLMCall]:
        """Newest first."""
        stmt = select(LLMCall)
        if run_id is not None:
            stmt = stmt.where(LLMCall.run_id == run_id)
        if pipeline_run_id is not None:
            stmt = stmt.where(LLMCall.pipeline_run_id == pipeline_run_id)
        if agent is not None:
            stmt = stmt.where(LLMCall.agent == agent)
        stmt = stmt.order_by(LLMCall.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())
