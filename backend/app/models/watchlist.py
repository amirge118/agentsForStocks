"""
WatchlistItem — the symbols the daily pipeline analyses, in display/run order.

The database is the source of truth; the WATCHLIST setting only seeds the table once
(migration 0005), so a list edited from the dashboard survives restarts.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.models.base import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.position}:{self.symbol}>"
