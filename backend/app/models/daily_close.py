"""
DailyClose — a symbol's close for one finished session, split- but not dividend-adjusted.
A past close doesn't change, so it is fetched once and read from here after: the last
known price when the source fails, and later the portfolio's value over time.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyClose(Base):
    __tablename__ = "daily_closes"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    def __repr__(self) -> str:
        return f"<DailyClose {self.symbol} {self.day}: {self.close}>"
