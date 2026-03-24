"""
Retry + timeout wrapper for all external API calls.

Every call to yfinance, Anthropic, or any external HTTP service
MUST go through with_retry(). Never call external services bare.

Usage:
    price = await with_retry(lambda: fetch_yfinance_info(symbol))
    analysis = await with_retry(lambda: call_claude(prompt), max_attempts=2)
"""
import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_ATTEMPTS = 3
_DEFAULT_TIMEOUT = 10.0  # seconds per attempt
_BASE_BACKOFF = 1.0      # seconds — doubles each retry: 1s, 2s, 4s


async def with_retry(
    fn: Callable[[], T],
    max_attempts: int = _DEFAULT_ATTEMPTS,
    timeout: float = _DEFAULT_TIMEOUT,
    label: str = "external_api",
) -> T:
    """
    Run fn() with exponential backoff retry and per-attempt timeout.
    fn must be a zero-arg callable (sync or async).
    Raises RuntimeError after all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await asyncio.wait_for(fn(), timeout=timeout)  # type: ignore[arg-type]
            else:
                # Sync function — run in thread to avoid blocking the loop
                return await asyncio.wait_for(
                    asyncio.to_thread(fn), timeout=timeout
                )
        except asyncio.TimeoutError as exc:
            last_exc = exc
            logger.warning(
                "%s timed out (attempt %d/%d, timeout=%.1fs)",
                label, attempt, max_attempts, timeout,
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "%s error (attempt %d/%d): %s",
                label, attempt, max_attempts, exc,
            )

        if attempt < max_attempts:
            backoff = _BASE_BACKOFF * (2 ** (attempt - 1))
            logger.debug("%s backing off %.1fs before retry", label, backoff)
            await asyncio.sleep(backoff)

    raise RuntimeError(
        f"{label} failed after {max_attempts} attempts. Last error: {last_exc}"
    ) from last_exc
