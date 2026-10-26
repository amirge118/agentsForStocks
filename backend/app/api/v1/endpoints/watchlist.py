"""
Watchlist endpoints — the symbols the daily pipeline analyses:
  GET    /watchlist            — the list, in order
  POST   /watchlist            — add a symbol at the end
  DELETE /watchlist/{symbol}   — remove a symbol (its stored analyses stay)
  PUT    /watchlist/order      — reorder (body: every symbol, in the new order)
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, symbol_param
from app.repositories.watchlist import (
    DuplicateSymbolError,
    WatchlistFullError,
    WatchlistRepository,
)
from app.schemas.api import WatchlistAdd, WatchlistItemOut, WatchlistOrder

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(session: AsyncSession = Depends(get_session)) -> list[WatchlistItemOut]:
    return [WatchlistItemOut.model_validate(i) for i in await WatchlistRepository(session).items()]


@router.post(
    "",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Already on the watchlist"}},
)
async def add_to_watchlist(
    body: WatchlistAdd, session: AsyncSession = Depends(get_session)
) -> WatchlistItemOut:
    try:
        item = await WatchlistRepository(session).add(body.symbol)
    except DuplicateSymbolError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except WatchlistFullError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return WatchlistItemOut.model_validate(item)


@router.delete(
    "/{symbol}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Not on the watchlist"}},
)
async def remove_from_watchlist(
    symbol: str = Depends(symbol_param), session: AsyncSession = Depends(get_session)
) -> Response:
    if not await WatchlistRepository(session).remove(symbol):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{symbol} is not on the watchlist")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/order", response_model=list[WatchlistItemOut])
async def reorder_watchlist(
    body: WatchlistOrder, session: AsyncSession = Depends(get_session)
) -> list[WatchlistItemOut]:
    try:
        items = await WatchlistRepository(session).reorder(body.symbols)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return [WatchlistItemOut.model_validate(i) for i in items]
