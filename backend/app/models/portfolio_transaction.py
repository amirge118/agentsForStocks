"""
PortfolioTransaction — one entry of the portfolio ledger (app/domain/portfolio.py).
Holdings, cash and P/L are derived from these rows, never stored. Amounts are Numeric:
money in floats gathers rounding errors.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.models.base import Base

MONEY = Numeric(18, 6)


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(10), nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_portfolio_transactions_trade_date", "trade_date"),)

    def __repr__(self) -> str:
        return f"<PortfolioTransaction {self.id} {self.trade_date} {self.kind} {self.symbol}>"
