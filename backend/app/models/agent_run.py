"""
AgentRun — one row per agent execution (completed, skipped or failed).

agent_results holds the latest result per (agent, symbol, day); agent_runs is the
audit trail that also records failures, so operators and the API can see what
happened in each pipeline run.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    pipeline_run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    agent_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # completed | skipped | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_type}/{self.symbol} {self.run_date} {self.status}>"
