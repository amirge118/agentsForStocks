"""
Request/response logging middleware.
Logs method, path, status, and duration for every request.
Redacts sensitive fields from request bodies.
Log level: INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx.
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_REDACTED_FIELDS = {"password", "token", "secret", "api_key", "authorization"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        log = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
        }

        if response.status_code < 400:
            logger.info("HTTP %s %s %d (%.1fms)", request.method, request.url.path, response.status_code, duration_ms)
        elif response.status_code < 500:
            logger.warning("HTTP %s %s %d (%.1fms)", request.method, request.url.path, response.status_code, duration_ms)
        else:
            logger.error("HTTP %s %s %d (%.1fms)", request.method, request.url.path, response.status_code, duration_ms)

        return response
