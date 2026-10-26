"""
LLM ledger endpoints:
  GET /llm/usage                 — tokens and cost per agent / model / provider / day / prompt
  GET /llm/providers             — configured providers: chain order, free-tier limits, use today
  GET /llm/calls                 — individual calls, newest first (filter by run or agent)
  GET /runs/{run_id}/llm-calls   — every call one agent run made, with the exact prompts
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session
from app.container import Container
from app.core.clock import utcnow
from app.llm.quota import QuotaLimits, day_start
from app.repositories.llm_calls import GroupBy, LLMCallRepository
from app.schemas.api import LLMCallOut, LLMProviderOut, LLMUsageReport, LLMUsageRow

router = APIRouter(tags=["llm"])


@router.get("/llm/usage", response_model=LLMUsageReport)
async def llm_usage(
    days: int = Query(default=7, ge=1, le=365),
    group_by: GroupBy = Query(default="agent"),
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


@router.get("/llm/providers", response_model=list[LLMProviderOut])
async def llm_providers(
    container: Container = Depends(get_container),
    session: AsyncSession = Depends(get_session),
) -> list[LLMProviderOut]:
    """Usage today comes from the ledger, so it includes the worker's scheduled run."""
    llm = container.llm
    order = llm.chain_order()
    repo = LLMCallRepository(session)
    now = utcnow()
    out = []
    for client in llm.providers():
        limits = client.quota.limits if client.quota is not None else QuotaLimits()
        start = day_start(limits.reset_tz, now)
        requests, tokens = await repo.provider_totals(client.name, start)
        out.append(
            LLMProviderOut(
                name=client.name,
                model=client.default_model,
                structured_mode=client.structured_mode,
                chain_position=order.index(client.name) + 1 if client.name in order else None,
                rpm=limits.rpm,
                tpm=limits.tpm,
                rpd=limits.rpd,
                tpd=limits.tpd,
                day_start=start,
                day_requests=requests,
                day_tokens=tokens,
            )
        )
    return out
