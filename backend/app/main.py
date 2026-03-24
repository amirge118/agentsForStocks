"""
FastAPI application entrypoint.
Starts the agent scheduler on startup and shuts it down cleanly on exit.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.scheduler import register_all_agents, scheduler
from app.middleware.request_logging import RequestLoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    register_all_agents()
    scheduler.start()
    logger.info("Agent scheduler started")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Agent scheduler stopped")


app = FastAPI(
    title="agentsForStocks",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggingMiddleware)

# Routers — add here as endpoints are implemented
# from app.api.v1.endpoints import agents, stocks
# app.include_router(agents.router, prefix="/api/v1")
# app.include_router(stocks.router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
