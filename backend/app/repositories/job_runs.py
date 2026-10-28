"""JobRunRepository — executions of the scheduled jobs."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.job_run import JobRun, JobStatus


class JobRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, job_id: str) -> JobRun:
        run = JobRun(id=str(uuid4()), job_id=job_id, started_at=utcnow(), status="running")
        self._session.add(run)
        await self._session.flush()
        return run

    async def finish(self, run_id: str, status: JobStatus, detail: str | None = None) -> None:
        run = await self._session.get(JobRun, run_id)
        if run is not None:
            run.status = status
            run.finished_at = utcnow()
            run.detail = detail

    async def first(self, job_id: str) -> JobRun | None:
        stmt = select(JobRun).where(JobRun.job_id == job_id).order_by(JobRun.started_at).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def latest(self, job_id: str, since: datetime | None = None) -> JobRun | None:
        """The most recent run of `job_id` (started at or after `since`, when given)."""
        stmt = select(JobRun).where(JobRun.job_id == job_id)
        if since is not None:
            stmt = stmt.where(JobRun.started_at >= since)
        stmt = stmt.order_by(JobRun.started_at.desc()).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()
