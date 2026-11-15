"""
Portfolio endpoints — the ledger and what it adds up to (app/domain/portfolio.py):
  GET    /portfolio                     — cash, holdings at cost, realised P/L
  GET    /portfolio/transactions        — the ledger, newest first
  POST   /portfolio/transactions        — record one entry
  PUT    /portfolio/transactions/{id}   — change an entry
  DELETE /portfolio/transactions/{id}   — remove an entry

A write that would ever sell shares not held, or spend cash not there, is refused (422)
and nothing changes. A symbol bought joins the watchlist, so the agents analyse it.
Amounts are the person's own: they are never logged or sent to a model.
"""

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session
from app.container import Container
from app.domain.portfolio import WITH_SHARES, Entry, Ledger, LedgerError
from app.models.portfolio_transaction import PortfolioTransaction
from app.repositories.portfolio import PortfolioRepository, TransactionNotFoundError
from app.repositories.watchlist import (
    DuplicateSymbolError,
    WatchlistFullError,
    WatchlistRepository,
)
from app.schemas.api import PortfolioOut, PositionOut, TransactionIn, TransactionOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_REFUSED = {422: {"description": "Breaks a ledger rule, e.g. sells shares not held"}}
_MISSING = {404: {"description": "No such transaction"}}


@router.get("", response_model=PortfolioOut)
async def get_portfolio(session: AsyncSession = Depends(get_session)) -> PortfolioOut:
    return _portfolio_out(await PortfolioRepository(session).ledger())


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(session: AsyncSession = Depends(get_session)) -> list[TransactionOut]:
    return [_transaction_out(row) for row in await PortfolioRepository(session).rows()]


@router.post(
    "/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    responses=_REFUSED,
)
async def add_transaction(
    body: TransactionIn,
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> TransactionOut:
    await _check_ticker(body, session, container)
    try:
        row = await PortfolioRepository(session).add(_entry(body), body.note)
    except LedgerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await _watch(body, session)
    await session.commit()
    return _transaction_out(row)


@router.put(
    "/transactions/{transaction_id}",
    response_model=TransactionOut,
    responses={**_REFUSED, **_MISSING},
)
async def update_transaction(
    transaction_id: int,
    body: TransactionIn,
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> TransactionOut:
    await _check_ticker(body, session, container)
    try:
        row = await PortfolioRepository(session).update(transaction_id, _entry(body), body.note)
    except TransactionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except LedgerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await _watch(body, session)
    await session.commit()
    return _transaction_out(row)


@router.delete(
    "/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_REFUSED, **_MISSING},
)
async def delete_transaction(
    transaction_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    try:
        await PortfolioRepository(session).delete(transaction_id)
    except TransactionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except LedgerError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"a later entry depends on this one: {exc}"
        ) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _check_ticker(body: TransactionIn, session: AsyncSession, container: Container) -> None:
    """A typo would otherwise sit in the ledger and fail every agent. Known symbols skip it."""
    if body.symbol is None or body.kind not in WITH_SHARES:
        return
    if body.symbol in await WatchlistRepository(session).symbols():
        return
    if await container.ticker_exists(body.symbol) is False:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{body.symbol}: no market data for this ticker — check the symbol",
        )


async def _watch(body: TransactionIn, session: AsyncSession) -> None:
    """Shares bought or brought in join the watchlist; selling out leaves it to the person."""
    if body.symbol is None or body.kind not in ("BUY", "TRANSFER_IN"):
        return
    try:
        await WatchlistRepository(session).add(body.symbol)
    except DuplicateSymbolError:
        pass
    except WatchlistFullError:
        logger.warning(
            "Watchlist full: a held symbol isn't analysed", extra={"symbol": body.symbol}
        )


def _entry(body: TransactionIn) -> Entry:
    return Entry(
        trade_date=body.trade_date,
        kind=body.kind,
        symbol=body.symbol,
        shares=body.shares,
        price=body.price,
        fee=body.fee,
        amount=body.amount,
    )


def _num(value: Decimal) -> float:
    return float(round(value, 6))


def _maybe(value: Decimal | None) -> float | None:
    return None if value is None else _num(value)


def _transaction_out(row: PortfolioTransaction) -> TransactionOut:
    return TransactionOut(
        id=row.id,
        trade_date=row.trade_date,
        kind=row.kind,  # type: ignore[arg-type]  # written from a validated Kind
        symbol=row.symbol,
        shares=_maybe(row.shares),
        price=_maybe(row.price),
        fee=_num(row.fee),
        amount=_maybe(row.amount),
        note=row.note,
        created_at=row.created_at,
    )


def _portfolio_out(ledger: Ledger) -> PortfolioOut:
    positions = [
        PositionOut(
            symbol=symbol,
            shares=_num(p.shares),
            avg_cost=_num(p.avg_cost or Decimal(0)),
            cost_basis=_num(p.cost),
            realised_pnl=_num(p.realised),
            dividends=_num(p.dividends),
        )
        for symbol, p in sorted(ledger.held.items(), key=lambda item: -item[1].cost)
    ]
    return PortfolioOut(
        cash=_num(ledger.cash),
        cost_basis=_num(ledger.cost_basis),
        deposited=_num(ledger.deposited),
        transferred_in=_num(ledger.transferred_in),
        realised_pnl=_num(ledger.realised),
        dividends=_num(ledger.dividends),
        fees=_num(ledger.fees),
        positions=positions,
    )
