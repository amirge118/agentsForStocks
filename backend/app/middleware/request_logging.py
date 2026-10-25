"""
Request/response logging middleware.
Logs method, path, status, and duration for every request.
Request bodies are never logged, so secrets (password, token, secret, api_key,
authorization) cannot leak; query strings are logged with those keys redacted.
Log level: INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REDACTED_FIELDS = {"password", "token", "secret", "api_key", "apikey", "authorization"}


def redact_query(params: dict[str, str]) -> dict[str, str]:
    return {k: ("***" if k.lower() in REDACTED_FIELDS else v) for k, v in params.items()}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        context = {
            "method": request.method,
            "path": request.url.path,
            "query": redact_query(dict(request.query_params)),
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
        }
        if response.status_code < 400:
            level = logging.INFO
        elif response.status_code < 500:
            level = logging.WARNING
        else:
            level = logging.ERROR
        logger.log(
            level,
            "HTTP %s %s %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra=context,
        )
        return response
