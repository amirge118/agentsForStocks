"""
LLM ledger endpoints:
  GET /llm/usage                 — tokens and cost per agent / model / day / prompt version
  GET /llm/calls                 — individual calls, newest first (filter by run or agent)
  GET /runs/{run_id}/llm-calls   — every call one agent run made, with the exact prompts
"""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.clock import utcnow
from app.repositories.llm_calls import LLMCallRepository
from app.schemas.api import LLMCallOut, LLMUsageReport, LLMUsageRow

router = APIRouter(tags=["llm"])


@router.get("/llm/usage", response_model=LLMUsageReport)
async def llm_usage(
    days: int = Query(default=7, ge=1, le=365),
    group_by: Literal["agent", "model", "day", "prompt_version"] = Query(default="agent"),
    session: AsyncSession = Depends(get_session),
) -> LLMUsageReport:
    since = utcnow() - timedelta(days=days)
    rows = await LLMCallRepository(session).usage(since=since, group_by=group_by)
    return LLMUsageReport(
        since=since,
        group_by=group_by,
        rows=[LLMUsageRow.model_validate(r) for r in rows],
        total_calls=sum(r.calls for r in rows),
        total_input_tokens=sum(
            r.input_tokens + r.cache_read_tokens + r.cache_write_tokens for r in rows
        ),
        total_output_tokens=sum(r.output_tokens for r in rows),
        total_cost_usd=round(sum(r.cost_usd for r in rows), 6),
    )


@router.get("/llm/calls", response_model=list[LLMCallOut])
async def list_llm_calls(
    run_id: str | None = Query(default=None),
    pipeline_run_id: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[LLMCallOut]:
    calls = await LLMCallRepository(session).list(
        run_id=run_id, pipeline_run_id=pipeline_run_id, agent=agent, limit=limit
    )
    return [LLMCallOut.model_validate(c) for c in calls]


@router.get("/runs/{run_id}/llm-calls", response_model=list[LLMCallOut])
async def run_llm_calls(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> list[LLMCallOut]:
    calls = await LLMCallRepository(session).list(run_id=run_id, limit=500)
    return [LLMCallOut.model_validate(c) for c in reversed(calls)]  # in call order
