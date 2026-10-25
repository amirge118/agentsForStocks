"""
FastAPI application entrypoint.
Builds the dependency container, starts the agent scheduler on startup and
shuts everything down cleanly on exit.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.scheduler import register_jobs, scheduler
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
    app.state.container = container
    register_jobs(container)
    scheduler.start()
    logger.info("Agent scheduler started")
    yield
    scheduler.shutdown(wait=False)
    await container.aclose()
    logger.info("Agent scheduler stopped")


app = FastAPI(title="agentsForStocks", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
