"""
Retry with exponential backoff and a per-attempt timeout.

Only transient failures are retried: timeouts and RetryableError. Anything else
(bad API key, 404, a bug) fails immediately — retrying it just burns quota.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.providers.errors import ProviderError, RetryableError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    timeout_seconds: float = 10.0
    base_backoff_seconds: float = 1.0  # doubles each retry: 1s, 2s, 4s

    def backoff(self, attempt: int) -> float:
        return self.base_backoff_seconds * (2 ** (attempt - 1))


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    label: str,
) -> T:
    """Await fn() under the policy. Raises ProviderError once attempts are exhausted."""
    last_exc: Exception | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await asyncio.wait_for(fn(), timeout=policy.timeout_seconds)
        except (TimeoutError, RetryableError) as exc:
            last_exc = exc
            logger.warning(
                "%s failed (attempt %d/%d): %s",
                label,
                attempt,
                policy.max_attempts,
                exc or "timeout",
            )
        if attempt < policy.max_attempts:
            await asyncio.sleep(policy.backoff(attempt))

    raise ProviderError(f"{label} failed after {policy.max_attempts} attempts") from last_exc
