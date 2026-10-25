"""FastAPI dependencies. Everything comes from the container on app.state, so tests can swap it."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.symbols import validate_symbol


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_container(request).session_factory() as session:
        yield session


def symbol_param(symbol: str = Path(description="Ticker, e.g. AAPL or BRK.B")) -> str:
    try:
        return validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
