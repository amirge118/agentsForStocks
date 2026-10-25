"""
All /api/v1 routes. Every route requires an API key (app/api/auth.py) and is
covered by RequestLoggingMiddleware (added in main.py). /health stays public.
"""

from fastapi import APIRouter, Depends

from app.api.auth import require_api_key
from app.api.v1.endpoints import agents, runs, symbols

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
api_router.include_router(agents.router)
api_router.include_router(symbols.router)
api_router.include_router(runs.router)
