"""All /api/v1 routes. Every route is covered by RequestLoggingMiddleware (added in main.py)."""

from fastapi import APIRouter

from app.api.v1.endpoints import agents, runs, symbols

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(agents.router)
api_router.include_router(symbols.router)
api_router.include_router(runs.router)
