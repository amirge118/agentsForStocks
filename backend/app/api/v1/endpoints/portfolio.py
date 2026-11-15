"""
Portfolio endpoints — the ledger and what it adds up to (app/domain/portfolio.py):
  GET    /portfolio                     — value at today's prices, cash, P/L, today's change
  GET    /portfolio/transactions        — the ledger, newest first
  POST   /portfolio/transactions        — record one entry
  PUT    /portfolio/transactions/{id}   — change an entry
  DELETE /portfolio/transactions/{id}   — remove an entry

Prices: one request for every holding, good for a minute while the market is open
and half an hour while it is closed. Each finished session's close is stored once
(daily_closes); when no quote comes back, the last stored close is used and marked stale.

A write that would ever sell shares not held, or spend cash not there, is refused (422)
and nothing changes. A symbol bought joins the watchlist, so the agents analyse it.
Amounts are the person's own: they are never logged or sent to a model.
"""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session
from app.container import Container
from app.core.clock import market_close, market_is_open, market_today, utcnow
from app.domain.portfolio import (
    WITH_SHARES,
    Entry,
    Holding,
    Ledger,
    LedgerError,
    Price,
    Valuation,
    valuation,
)
from app.models.portfolio_transaction import PortfolioTransaction
from app.providers.yfinance import Quote
from app.repositories.daily_closes import DailyCloseRepository
from app.repositories.portfolio import PortfolioRepository, TransactionNotFoundError
from app.repositories.watchlist import (
    DuplicateSymbolError,
    WatchlistFullError,
    WatchlistRepository,
)
from app.schemas.api import PortfolioOut, PositionOut, TransactionIn, TransactionOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

QUOTE_TTL_OPEN = 60.0
QUOTE_TTL_CLOSED = 30 * 60.0
_REFUSED = {422: {"description": "Breaks a ledger rule, e.g. sells shares not held"}}
_MISSING = {404: {"description": "No such transaction"}}


@router.get("", response_model=PortfolioOut)
async def get_portfolio(
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> PortfolioOut:
    ledger = await PortfolioRepository(session).ledger()
    prices = await _prices(list(ledger.held), session, container)
    return _portfolio_out(ledger, valuation(ledger, prices))


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


async def _prices(
    symbols: list[str], session: AsyncSession, container: Container
) -> dict[str, Price]:
    """Live quotes, their finished closes stored, and the last stored close for the rest."""
    if not symbols:
        return {}
    ttl = QUOTE_TTL_OPEN if market_is_open() else QUOTE_TTL_CLOSED
    quotes = await container.quotes(symbols, ttl)
    closes = DailyCloseRepository(session)
    for quote in quotes.values():
        await closes.save(quote.symbol, _finished(quote.closes))
    await session.commit()
    prices = {s: _live(q) for s, q in quotes.items()}
    missing = [s for s in symbols if s not in prices]
    for symbol, (day, close) in (await closes.latest(missing)).items():
        prices[symbol] = Price(close, None, day, stale=True)
    if missing:
        logger.warning("No live quote: using the last stored close", extra={"symbols": missing})
    return prices


def _finished(closes: tuple[tuple[date, float], ...]) -> list[tuple[date, float]]:
    """Today's bar is still moving until the close; earlier sessions are final."""
    today = market_today()
    closed = utcnow() >= market_close(today)
    return [(day, close) for day, close in closes if day < today or (day == today and closed)]


def _live(quote: Quote) -> Price:
    previous = quote.previous_close
    return Price(
        price=_decimal(quote.price),
        previous_close=None if previous is None else _decimal(previous),
        as_of=quote.as_of,
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


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


def _portfolio_out(ledger: Ledger, v: Valuation) -> PortfolioOut:
    return PortfolioOut(
        cash=_num(ledger.cash),
        holdings_value=_num(v.holdings_value),
        total_value=_num(v.total_value),
        unrealised_pnl=_num(v.unrealised),
        day_change=_num(v.day_change),
        day_change_pct=_maybe(v.day_change_pct),
        cost_basis=_num(ledger.cost_basis),
        deposited=_num(ledger.deposited),
        transferred_in=_num(ledger.transferred_in),
        realised_pnl=_num(ledger.realised),
        dividends=_num(ledger.dividends),
        fees=_num(ledger.fees),
        unpriced=v.unpriced,
        positions=[_position_out(h) for h in v.holdings],
    )


def _position_out(h: Holding) -> PositionOut:
    p = h.position
    unrealised_pct = (
        h.unrealised / p.cost * 100 if h.unrealised is not None and p.cost > 0 else None
    )
    return PositionOut(
        symbol=h.symbol,
        shares=_num(p.shares),
        avg_cost=_num(p.avg_cost or Decimal(0)),
        cost_basis=_num(p.cost),
        realised_pnl=_num(p.realised),
        dividends=_num(p.dividends),
        price=None if h.price is None else _num(h.price.price),
        price_as_of=None if h.price is None else h.price.as_of,
        price_stale=h.price is not None and h.price.stale,
        value=_maybe(h.value),
        unrealised_pnl=_maybe(h.unrealised),
        unrealised_pct=_maybe(unrealised_pct),
        day_change=_maybe(h.day_change),
        weight=_maybe(h.weight),
    )
