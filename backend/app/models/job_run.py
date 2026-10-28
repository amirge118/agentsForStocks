"""
JobRun — one execution of a scheduled job (app/agents/scheduler.py), so a run
that failed, or never started, shows up in /health instead of going unnoticed.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# partial: the job finished, but some of its work (e.g. agent runs) failed
JobStatus = Literal["running", "completed", "partial", "failed"]


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<JobRun {self.job_id} {self.started_at:%Y-%m-%d %H:%M} {self.status}>"
