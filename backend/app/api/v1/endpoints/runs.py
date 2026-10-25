"""
Pipeline endpoints:
  GET  /runs           — agent execution history (agent_runs), newest first
  POST /pipeline/runs  — start a pipeline run in the background (202 + pipeline_run_id)
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session
from app.container import Container
from app.core.symbols import validate_symbol
from app.repositories.agent_runs import AgentRunRepository
from app.schemas.api import AgentRunOut, PipelineRunAccepted, PipelineRunRequest

router = APIRouter(tags=["pipeline"])


@router.get("/runs", response_model=list[AgentRunOut])
async def list_runs(
    symbol: str | None = Query(default=None),
    run_date: date | None = Query(default=None),
    status_filter: Literal["completed", "skipped", "failed"] | None = Query(
        default=None, alias="status"
    ),
    pipeline_run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[AgentRunOut]:
    if symbol is not None:
        try:
            symbol = validate_symbol(symbol)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    runs = await AgentRunRepository(session).list(
        symbol=symbol,
        run_date=run_date,
        status=status_filter,
        pipeline_run_id=pipeline_run_id,
        limit=limit,
    )
    return [AgentRunOut.model_validate(run) for run in runs]


@router.post(
    "/pipeline/runs", response_model=PipelineRunAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def start_pipeline_run(
    body: PipelineRunRequest,
    container: Container = Depends(get_container),
) -> PipelineRunAccepted:
    symbols = body.symbols or container.settings.watchlist_symbols
    try:
        run = container.launcher.launch(symbols, body.agents, force=body.force)
    except (ValueError, KeyError) as exc:
        detail = exc.args[0] if exc.args else str(exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(detail)) from exc
    return PipelineRunAccepted(
        pipeline_run_id=run.pipeline_run_id,
        run_date=run.run_date,
        symbols=run.symbols,
        agents=run.agents,
        force=run.force,
    )
