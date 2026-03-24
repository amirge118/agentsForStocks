"""
AgentResult — stores every agent run output.
Unique constraint on (agent_type, symbol, run_date) enforces idempotency.
Re-running an agent for the same symbol on the same day upserts, not duplicates.
"""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentResult(Base):
    __tablename__ = "agent_results"
    __table_args__ = (
        UniqueConstraint("agent_type", "symbol", "run_date", name="uq_agent_symbol_date"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    agent_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AgentResult {self.agent_type}/{self.symbol} {self.run_date}>"
