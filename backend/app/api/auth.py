"""
API-key authentication for /api/v1.

Clients send `X-API-Key: <key>`. Keys come from the API_KEYS setting and are
compared in constant time. With no keys configured (development only — see
Settings) every request is allowed and a warning is logged once at startup.
"""

import hmac
import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.api.deps import get_container
from app.container import Container

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"

_api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key from the API_KEYS setting",
)


def _matches(candidate: str, keys: list[str]) -> bool:
    # Check every key so timing does not reveal which one (or whether any) matched
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(candidate.encode(), key.encode())
    return matched


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
    container: Container = Depends(get_container),
) -> None:
    settings = container.settings
    if not settings.auth_enabled:
        return
    if api_key is None or not _matches(api_key, settings.api_key_list):
        logger.warning(
            "Rejected API request with missing or invalid API key",
            extra={
                "path": request.url.path,
                "client": request.client.host if request.client else None,
            },
        )
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid API key",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
