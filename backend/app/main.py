"""
FastAPI application entrypoint.
Builds the dependency container, starts the daily pipeline scheduler on startup
and shuts everything down cleanly on exit.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.agents.scheduler import create_scheduler
from app.api.v1.router import api_router
from app.container import build_container
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.middleware.request_logging import RequestLoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container = build_container(settings, AsyncSessionLocal)
    scheduler = create_scheduler(container.orchestrator, settings.watchlist_symbols)
    app.state.container = container
    app.state.scheduler = scheduler
    scheduler.start()
    logger.info("Agent scheduler started")
    yield
    scheduler.shutdown(wait=False)
    await container.aclose()
    logger.info("Agent scheduler stopped")


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


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness + dependencies: 200 when the DB answers and the scheduler runs, else 503."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.container.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("Health check: database unavailable", extra={"error": str(exc)})
        checks["database"] = "unavailable"
    checks["scheduler"] = "ok" if request.app.state.scheduler.running else "stopped"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
