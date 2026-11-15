"""
Portfolio endpoints — the ledger and what it adds up to (app/domain/portfolio.py):
  GET    /portfolio                     — value at today's prices, cash, P/L, today's change
  GET    /portfolio/performance         — value over time, return vs the benchmark, the week
  GET    /portfolio/exposure            — sectors vs targets, risk, the agents' calls on it
  PUT    /portfolio/sector-targets      — replace the sector targets
  GET    /portfolio/transactions        — the ledger, newest first
  POST   /portfolio/transactions        — record one entry
  PUT    /portfolio/transactions/{id}   — change an entry
  DELETE /portfolio/transactions/{id}   — remove an entry

Prices: one request for every holding, good for a minute while the market is open
and half an hour while it is closed. Each finished session's close is stored once
(daily_closes); when no quote comes back, the last stored close is used and marked stale.
The performance view reads those stored closes; only a missing stretch is fetched.

A write that would ever sell shares not held, or spend cash not there, is refused (422)
and nothing changes. A symbol bought joins the watchlist, so the agents analyse it.
Amounts are the person's own: they are never logged or sent to a model.
"""

import logging
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_container, get_session
from app.container import Container
from app.core.clock import market_close, market_is_open, market_today, utcnow
from app.domain import exposure
from app.domain.performance import EMPTY, Mover, Performance, performance
from app.domain.portfolio import (
    WITH_SHARES,
    Entry,
    Holding,
    Ledger,
    LedgerError,
    Price,
    Valuation,
    replay,
    valuation,
)
from app.models.portfolio_transaction import PortfolioTransaction
from app.providers.yfinance import Quote
from app.repositories.agent_results import AgentResultRepository
from app.repositories.daily_closes import DailyCloseRepository
from app.repositories.portfolio import PortfolioRepository, TransactionNotFoundError
from app.repositories.sector_targets import SectorTargetRepository
from app.repositories.watchlist import (
    DuplicateSymbolError,
    WatchlistFullError,
    WatchlistRepository,
)
from app.schemas.api import (
    ActionShareOut,
    CallChangeOut,
    ExposureOut,
    MoverOut,
    PairOut,
    PerformanceOut,
    PerformancePointOut,
    PortfolioOut,
    PositionOut,
    RiskOut,
    SectorShareOut,
    SectorTargetIn,
    SectorTargetOut,
    TransactionIn,
    TransactionOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

QUOTE_TTL_OPEN = 60.0
QUOTE_TTL_CLOSED = 30 * 60.0
BACKFILL_MARGIN = timedelta(days=7)  # a benchmark close before the first entry, to start from
MAX_CLOSURE = timedelta(days=5)  # more days than this without a close: a hole to fetch
CORRELATION_LOOKBACK = timedelta(days=100)  # enough calendar days for 60 sessions
MAX_SECTOR_TARGETS = 50
ACTIONS = ("BUY", "HOLD", "SELL")
_REFUSED = {422: {"description": "Breaks a ledger rule, e.g. sells shares not held"}}
_MISSING = {404: {"description": "No such transaction"}}


@router.get("", response_model=PortfolioOut)
async def get_portfolio(
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> PortfolioOut:
    ledger = await PortfolioRepository(session).ledger()
    prices = await _prices(_quoted(ledger, container), session, container)
    return _portfolio_out(ledger, valuation(ledger, prices))


@router.get("/performance", response_model=PerformanceOut)
async def get_performance(
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> PerformanceOut:
    entries = await PortfolioRepository(session).entries()
    benchmark = container.settings.outcome_benchmark
    if not entries:
        return _performance_out(benchmark, EMPTY)
    today = market_today()
    start = min(e.trade_date for e in entries) - BACKFILL_MARGIN
    traded = {e.symbol for e in entries if e.kind in WITH_SHARES and e.symbol}
    symbols = sorted(traded | {benchmark})
    live = await _prices(_quoted(replay(entries), container), session, container)
    closes = await _closes(symbols, start, today, session, container)
    for symbol, price in live.items():
        if not price.stale:
            closes.setdefault(symbol, {})[price.as_of] = price.price
    sessions = closes.get(benchmark) or {d for c in closes.values() for d in c}
    return _performance_out(benchmark, performance(entries, closes, sessions, benchmark, today))


@router.get("/exposure", response_model=ExposureOut)
async def get_exposure(
    session: AsyncSession = Depends(get_session),
    container: Container = Depends(get_container),
) -> ExposureOut:
    ledger = await PortfolioRepository(session).ledger()
    v = valuation(ledger, await _prices(_quoted(ledger, container), session, container))
    held = list(ledger.held)
    sector_of, beta_of, calls = await _agents_on(held, session)
    today = market_today()
    closes = await _closes(held, today - CORRELATION_LOOKBACK, today, session, container)
    targets = await SectorTargetRepository(session).all()
    r = exposure.risk(v, beta_of, closes)
    return ExposureOut(
        sectors=[
            SectorShareOut(
                sector=s.sector,
                value=_num(s.value),
                weight=_num(s.weight),
                target=_maybe(s.target),
                drift=_maybe(s.drift),
                symbols=s.symbols,
            )
            for s in exposure.sectors(v, sector_of, targets)
        ],
        risk=RiskOut(
            largest_symbol=r.largest[0] if r.largest else None,
            largest_weight=_num(r.largest[1]) if r.largest else None,
            cash_weight=_maybe(r.cash_weight),
            beta=_maybe(r.beta),
            beta_coverage=_maybe(r.beta_coverage),
            together=[
                PairOut(
                    first=p.first,
                    second=p.second,
                    correlation=round(p.correlation, 4),
                    sessions=p.sessions,
                )
                for p in r.together
            ],
        ),
        actions=[
            ActionShareOut(
                action=a.action, value=_num(a.value), weight=_num(a.weight), symbols=a.symbols
            )
            for a in exposure.actions(v, calls)
        ],
        changed=[
            CallChangeOut(
                symbol=c.symbol,
                action=c.action,  # type: ignore[arg-type]  # one of ACTIONS (_agents_on)
                previous=c.previous,  # type: ignore[arg-type]  # same
                run_date=c.run_date,
            )
            for c in exposure.changed(calls)
        ],
    )


@router.put("/sector-targets", response_model=list[SectorTargetOut])
async def set_sector_targets(
    body: list[SectorTargetIn], session: AsyncSession = Depends(get_session)
) -> list[SectorTargetOut]:
    """Replaces every target: a sector left out has none after."""
    if len(body) > MAX_SECTOR_TARGETS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"at most {MAX_SECTOR_TARGETS} sector targets"
        )
    targets = {t.sector: t.target_pct for t in body}
    if len(targets) != len(body):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a sector is listed twice")
    saved = await SectorTargetRepository(session).replace(targets)
    await session.commit()
    return [SectorTargetOut(sector=s, target_pct=_num(p)) for s, p in sorted(saved.items())]


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


def _quoted(ledger: Ledger, container: Container) -> list[str]:
    """
    The holdings and the benchmark: the summary and the performance view ask for the same
    set, so they share one cached request a minute.
    """
    held = set(ledger.held)
    return sorted(held | {container.settings.outcome_benchmark}) if held else []


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


async def _closes(
    symbols: list[str], start: date, today: date, session: AsyncSession, container: Container
) -> dict[str, dict[date, Decimal]]:
    """
    The stored closes since `start`; a symbol with a hole longer than any market closure
    is fetched first, in one request for all of them, and stored. A failed fetch leaves
    the holes (the series carries the last close across them).
    """
    repo = DailyCloseRepository(session)
    stored = await repo.between(symbols, start, today)
    holes = {s: day for s in symbols if (day := _first_hole(stored.get(s, {}), start, today))}
    if not holes:
        return stored
    fetched = await container.daily_closes(list(holes), min(holes.values()), today)
    for symbol, bars in fetched.items():
        await repo.save(symbol, _finished(bars))
    await session.commit()
    if fetched:
        logger.info("Closes backfilled", extra={"symbols": sorted(fetched)})
    return await repo.between(symbols, start, today)


async def _agents_on(
    symbols: list[str], session: AsyncSession
) -> tuple[dict[str, str], dict[str, float | None], dict[str, exposure.Call]]:
    """
    Each holding's sector (broad_analysis), beta (risk) and latest call with the one before
    (recommendation), from what the agents stored. A symbol the company agents never ran on,
    but the others did, is a fund. One query per agent, plus one per call for the previous.
    """
    repo = AgentResultRepository(session)
    broad = await repo.latest_per_symbol("broad_analysis", symbols)
    risk = await repo.latest_per_symbol("risk", symbols)
    recs = await repo.latest_per_symbol("recommendation", symbols)
    techs = await repo.latest_per_symbol("technicals", symbols)
    sector_of: dict[str, str] = {}
    for symbol in symbols:
        sector = broad[symbol].result_json.get("sector") if symbol in broad else None
        if isinstance(sector, str) and sector.strip():
            sector_of[symbol] = sector.strip()[:64]
        elif symbol in techs and symbol not in recs:
            sector_of[symbol] = exposure.FUND
    beta_of = {s: _number(row.result_json.get("beta")) for s, row in risk.items()}
    calls: dict[str, exposure.Call] = {}
    for symbol, row in recs.items():
        action = row.result_json.get("action")
        if action not in ACTIONS:
            continue
        before = await repo.latest_before("recommendation", symbol, row.run_date)
        previous = before[1].get("action") if before else None
        calls[symbol] = exposure.Call(
            symbol, action, row.run_date, previous if previous in ACTIONS else None
        )
    return sector_of, beta_of, calls


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _first_hole(days: Iterable[date], start: date, today: date) -> date | None:
    points = [start, *sorted(days), today]
    return next((a for a, b in pairwise(points) if b - a > MAX_CLOSURE), None)


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


def _performance_out(benchmark: str, p: Performance) -> PerformanceOut:
    return PerformanceOut(
        benchmark=benchmark,
        since=p.series[0].day if p.series else None,
        total_return_pct=_maybe(p.total_return_pct),
        benchmark_return_pct=_maybe(p.benchmark_return_pct),
        week_start=p.week_start,
        week_change=_maybe(p.week_change),
        week_change_pct=_maybe(p.week_change_pct),
        gainers=[_mover_out(m) for m in p.gainers],
        losers=[_mover_out(m) for m in p.losers],
        series=[
            PerformancePointOut(
                day=v.day,
                value=_num(v.value),
                flow=_num(v.flow),
                index=_num(v.index),
                benchmark=_maybe(v.benchmark),
            )
            for v in p.series
        ],
    )


def _mover_out(m: Mover) -> MoverOut:
    return MoverOut(symbol=m.symbol, change=_num(m.change), change_pct=_num(m.change_pct))


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
