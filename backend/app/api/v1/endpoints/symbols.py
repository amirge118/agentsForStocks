"""
Symbol endpoints:
  GET /symbols                          — watchlist with each symbol's latest recommendation
  GET /symbols/{symbol}/recommendation  — latest recommendation for one symbol
  GET /symbols/{symbol}/results         — stored agent results (filter by agent / date)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session, symbol_param
from app.container import Container
from app.repositories.agent_results import AgentResultRepository
from app.schemas.api import AgentResultOut, Recommendation, SymbolOverview

router = APIRouter(prefix="/symbols", tags=["symbols"])

_RECOMMENDATION = "recommendation"


@router.get("", response_model=list[SymbolOverview])
async def list_symbols(
    container: Container = Depends(get_container),
    session: AsyncSession = Depends(get_session),
) -> list[SymbolOverview]:
    symbols = container.settings.watchlist_symbols
    latest = await AgentResultRepository(session).latest_per_symbol(_RECOMMENDATION, symbols)
    return [
        SymbolOverview(
            symbol=symbol,
            recommendation=(
                Recommendation.from_row(symbol, row.run_date, row.updated_at, row.result_json)
                if (row := latest.get(symbol))
                else None
            ),
        )
        for symbol in symbols
    ]


@router.get("/{symbol}/recommendation", response_model=Recommendation)
async def get_recommendation(
    symbol: str = Depends(symbol_param),
    session: AsyncSession = Depends(get_session),
) -> Recommendation:
    latest = await AgentResultRepository(session).latest_per_symbol(_RECOMMENDATION, [symbol])
    row = latest.get(symbol)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No recommendation for {symbol} yet")
    return Recommendation.from_row(symbol, row.run_date, row.updated_at, row.result_json)


@router.get("/{symbol}/results", response_model=list[AgentResultOut])
async def list_results(
    symbol: str = Depends(symbol_param),
    agent: str | None = Query(default=None, description="Only this agent's results"),
    run_date: date | None = Query(default=None, description="Only this market date"),
    limit: int = Query(default=50, ge=1, le=500),
    container: Container = Depends(get_container),
    session: AsyncSession = Depends(get_session),
) -> list[AgentResultOut]:
    if agent is not None and agent not in container.registry.names():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown agent {agent!r}")
    rows = await AgentResultRepository(session).list_for_symbol(
        symbol, agent_type=agent, run_date=run_date, limit=limit
    )
    return [AgentResultOut.model_validate(row) for row in rows]
