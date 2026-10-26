"""WatchlistRepository — the analysed symbols, kept in a stable order."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.watchlist import WatchlistItem

# Same cap as a manual run (PipelineRunRequest.symbols): one daily run stays bounded
MAX_SYMBOLS = 50


class DuplicateSymbolError(ValueError):
    pass


class WatchlistFullError(ValueError):
    pass


class WatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def items(self) -> list[WatchlistItem]:
        stmt = select(WatchlistItem).order_by(WatchlistItem.position, WatchlistItem.symbol)
        return list((await self._session.execute(stmt)).scalars().all())

    async def symbols(self) -> list[str]:
        return [item.symbol for item in await self.items()]

    async def add(self, symbol: str) -> WatchlistItem:
        """Append a (validated) symbol at the end of the list."""
        if await self._session.get(WatchlistItem, symbol) is not None:
            raise DuplicateSymbolError(f"{symbol} is already on the watchlist")
        count, last = (
            await self._session.execute(
                select(func.count(), func.max(WatchlistItem.position)).select_from(WatchlistItem)
            )
        ).one()
        if count >= MAX_SYMBOLS:
            raise WatchlistFullError(f"The watchlist holds at most {MAX_SYMBOLS} symbols")
        item = WatchlistItem(symbol=symbol, position=0 if last is None else last + 1)
        self._session.add(item)
        await self._session.flush()
        return item

    async def remove(self, symbol: str) -> bool:
        """Remove a symbol (its stored analyses stay). False if it wasn't listed."""
        item = await self._session.get(WatchlistItem, symbol)
        if item is None:
            return False
        await self._session.delete(item)
        await self._session.flush()
        return True

    async def reorder(self, symbols: list[str]) -> list[WatchlistItem]:
        """Set the order; `symbols` must be exactly the current set."""
        items = {item.symbol: item for item in await self.items()}
        if len(symbols) != len(set(symbols)) or set(symbols) != set(items):
            raise ValueError("The new order must list every watchlist symbol exactly once")
        for position, symbol in enumerate(symbols):
            items[symbol].position = position
        await self._session.flush()
        return [items[s] for s in symbols]
