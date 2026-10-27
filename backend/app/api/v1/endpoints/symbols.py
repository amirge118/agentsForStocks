"""
Symbol endpoints:
  GET /symbols                          — watchlist with each symbol's latest recommendation
  GET /symbols/{symbol}/recommendation  — latest recommendation for one symbol
  GET /symbols/{symbol}/results         — stored agent results (filter by agent / date)
  GET /symbols/{symbol}/prices          — daily OHLCV + SMA20/50 + RSI14 for the price chart
  GET /symbols/{symbol}/outcomes        — how past recommendations turned out (track record)
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session, symbol_param
from app.api.v1.endpoints.outcomes import horizon_param
from app.container import Container
from app.domain.outcomes import track_stats
from app.domain.price_chart import fetch_period, price_bars
from app.providers.errors import ProviderError
from app.repositories.agent_results import AgentResultRepository
from app.repositories.decision_outcomes import DecisionOutcomeRepository
from app.repositories.watchlist import WatchlistRepository
from app.schemas.api import (
    AgentResultOut,
    OutcomeCallOut,
    PriceBarOut,
    PriceHistory,
    Recommendation,
    SymbolOverview,
    SymbolTrackRecord,
    TrackStatsOut,
)

router = APIRouter(prefix="/symbols", tags=["symbols"])

_RECOMMENDATION = "recommendation"


@router.get("", response_model=list[SymbolOverview])
async def list_symbols(session: AsyncSession = Depends(get_session)) -> list[SymbolOverview]:
    symbols = await WatchlistRepository(session).symbols()
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown agent {agent!r}")
    rows = await AgentResultRepository(session).list_for_symbol(
        symbol, agent_type=agent, run_date=run_date, limit=limit
    )
    return [AgentResultOut.model_validate(row) for row in rows]


@router.get(
    "/{symbol}/prices",
    response_model=PriceHistory,
    responses={502: {"description": "The price provider is unavailable"}},
)
async def get_prices(
    symbol: str = Depends(symbol_param),
    price_range: Literal["1M", "3M", "6M", "1Y"] = Query(default="6M", alias="range"),
    container: Container = Depends(get_container),
) -> PriceHistory:
    # Through YFinanceClient: rate limit, retries and the shared TTL cache
    try:
        history = await container.agent_context.yfinance.get_history(
            symbol, period=fetch_period(price_range), interval="1d"
        )
    except ProviderError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Price data for {symbol} is unavailable"
        ) from exc
    bars = [PriceBarOut.model_validate(bar) for bar in price_bars(history, price_range)]
    return PriceHistory(symbol=symbol, range=price_range, bars=bars)


@router.get("/{symbol}/outcomes", response_model=SymbolTrackRecord)
async def get_outcomes(
    symbol: str = Depends(symbol_param),
    horizon: int = Depends(horizon_param),
    limit: int = Query(default=30, ge=1, le=200, description="Most recent settled calls"),
    session: AsyncSession = Depends(get_session),
) -> SymbolTrackRecord:
    repo = DecisionOutcomeRepository(session)
    rows = await repo.scored_calls(horizon, agent=_RECOMMENDATION, symbol=symbol)
    calls = [call for _, call in rows]
    counts = await repo.status_counts(horizon, symbol=symbol)
    return SymbolTrackRecord(
        symbol=symbol,
        horizon=horizon,
        overall=TrackStatsOut.from_stats(track_stats(calls)),
        pending=counts.get("pending", 0),
        calls=[OutcomeCallOut.from_call(c) for c in calls[:limit]],
    )
