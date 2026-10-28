"""
FastAPI application entrypoint.
Builds the dependency container and, when SCHEDULER_ENABLED and RUN_SCHEDULER are
both on, starts the scheduled jobs (in production they run in app/worker.py).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.agents.scheduler import build_scheduler, job_health
from app.api.v1.router import api_router
from app.container import build_container
from app.core.clock import market_today
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal, engine
from app.middleware.request_logging import RequestLoggingMiddleware
from app.observability import metrics
from app.observability.telemetry import configure_telemetry

configure_logging(settings.log_format, settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container = build_container(settings, AsyncSessionLocal)
    if not settings.auth_enabled:
        logger.warning("API authentication is DISABLED (no API_KEYS) — development only")
    app.state.container = container
    app.state.scheduler = None
    if settings.run_scheduler:
        app.state.scheduler = build_scheduler(
            settings,
            container.orchestrator,
            container.session_factory,
            settler=container.settler,
            lock=container.lock,
            registry=container.registry,
        )
    if app.state.scheduler is not None:
        app.state.scheduler.start()
        logger.info("Agent scheduler started in the API process")
    yield
    if app.state.scheduler is not None:
        app.state.scheduler.shutdown(wait=False)
        logger.info("Agent scheduler stopped")
    await container.aclose()
    telemetry.shutdown()


app = FastAPI(title="agentsForStocks", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(api_router)
telemetry = configure_telemetry(
    settings, service_name="agentsforstocks-api", app=app, engine=engine
)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """
    Liveness + dependencies: 200 when the DB answers and the in-process scheduler
    (if this process runs one) is running, else 503. With the scheduler on, `jobs`
    says how each job's latest due run went (ok, running, partial, failed, missed);
    a missed or failed run is logged but doesn't make the process unhealthy —
    restarting the API wouldn't bring the run back.
    """
    checks: dict[str, str] = {}
    jobs: dict[str, str] = {}
    try:
        async with request.app.state.container.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Health check: database unavailable", extra={"error": str(exc)})
        checks["database"] = "unavailable"
    scheduler = request.app.state.scheduler
    if not settings.scheduler_enabled:
        checks["scheduler"] = "disabled"  # SCHEDULER_ENABLED=false: nothing runs on its own
    elif scheduler is None:
        checks["scheduler"] = "external"  # runs in app.worker, not in this process
    else:
        checks["scheduler"] = "ok" if scheduler.running else "stopped"

    if settings.scheduler_enabled and checks["database"] == "ok":
        try:
            jobs = dict(await job_health(settings, request.app.state.container.session_factory))
            _report_job_problems(jobs)
        except Exception as exc:
            logger.error("Health check: job states unavailable", extra={"error": str(exc)})

    healthy = checks["database"] == "ok" and checks["scheduler"] != "stopped"
    content: dict[str, object] = {"status": "ok" if healthy else "degraded", "checks": checks}
    if jobs:
        content["jobs"] = jobs
    return JSONResponse(status_code=200 if healthy else 503, content=content)


_reported: set[tuple[str, str, str]] = set()


def _report_job_problems(jobs: dict[str, str]) -> None:
    """Log (and count) a missed or failed job once per day and state, not on every poll."""
    day = market_today().isoformat()
    for job, state in jobs.items():
        if state in ("missed", "failed") and (job, state, day) not in _reported:
            _reported.add((job, state, day))
            metrics.scheduled_job_problems.add(1, {"job": job, "state": state})
            logger.error("Scheduled job %s: %s", job, state, extra={"job": job, "state": state})
