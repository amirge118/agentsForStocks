"""
DecisionOutcome — what happened to a symbol after a day the agents judged it.

One row per (symbol, decision_date, horizon_days). The price outcome is the same
for every agent, so it is stored once and joined to agent_results on
(symbol, run_date) to score any agent's signal. Settled by app/pipeline/settlement.py.
"""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "decision_date", "horizon_days", name="uq_outcome_symbol_date_horizon"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)  # OutcomeStatus
    # Filled when settled; returns are fractions (0.05 = +5%)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nights the window should have traded but the prices were not there
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DecisionOutcome {self.symbol} {self.decision_date} "
            f"+{self.horizon_days}d {self.status}>"
        )
