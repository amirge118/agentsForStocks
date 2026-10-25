import asyncio
import time

import pytest

from app.core.symbols import validate_symbol
from app.providers.cache import TTLCache
from app.providers.errors import ProviderError, RetryableError
from app.providers.rate_limit import RateLimiter
from app.providers.retry import RetryPolicy, with_retry

FAST = RetryPolicy(max_attempts=3, timeout_seconds=1.0, base_backoff_seconds=0.0)


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [("aapl", "AAPL"), (" BRK.B ", "BRK.B")])
def test_validate_symbol_normalises(raw: str, expected: str) -> None:
    assert validate_symbol(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "AAPL;DROP", "../etc", "TOOLONGSYMBOL"])
def test_validate_symbol_rejects_unsafe_input(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_symbol(raw)


@pytest.mark.unit
async def test_retry_recovers_from_transient_errors() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableError("503")
        return "ok"

    assert await with_retry(flaky, FAST, "test") == "ok"
    assert calls == 3


@pytest.mark.unit
async def test_retry_gives_up_with_provider_error() -> None:
    async def always_down() -> str:
        raise RetryableError("503")

    with pytest.raises(ProviderError, match="after 3 attempts"):
        await with_retry(always_down, FAST, "test")


@pytest.mark.unit
async def test_retry_does_not_retry_permanent_errors() -> None:
    calls = 0

    async def bad_key() -> str:
        nonlocal calls
        calls += 1
        raise ProviderError("HTTP 401")

    with pytest.raises(ProviderError, match="401"):
        await with_retry(bad_key, FAST, "test")
    assert calls == 1


@pytest.mark.unit
async def test_retry_times_out_slow_calls() -> None:
    async def slow() -> str:
        await asyncio.sleep(1)
        return "late"

    policy = RetryPolicy(max_attempts=2, timeout_seconds=0.01, base_backoff_seconds=0.0)
    with pytest.raises(ProviderError):
        await with_retry(slow, policy, "test")


@pytest.mark.unit
def test_backoff_doubles() -> None:
    assert [RetryPolicy().backoff(a) for a in (1, 2, 3)] == [1.0, 2.0, 4.0]


@pytest.mark.unit
async def test_rate_limiter_spaces_calls_per_domain() -> None:
    limiter = RateLimiter({"slow.example": 20.0})  # 50ms interval
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire("slow.example")
    assert time.monotonic() - start >= 0.09

    start = time.monotonic()
    await limiter.acquire("other.example")  # different domain — not delayed
    assert time.monotonic() - start < 0.05


@pytest.mark.unit
async def test_cache_returns_cached_value_until_ttl() -> None:
    cache = TTLCache(ttl_seconds=60)
    calls = 0

    async def load() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_load("k", load) == 1
    assert await cache.get_or_load("k", load) == 1
    cache.clear()
    assert await cache.get_or_load("k", load) == 2


@pytest.mark.unit
async def test_cache_deduplicates_concurrent_loads() -> None:
    cache = TTLCache(ttl_seconds=60)
    calls = 0

    async def load() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "profile"

    results = await asyncio.gather(*(cache.get_or_load("p", load) for _ in range(5)))
    assert results == ["profile"] * 5
    assert calls == 1


@pytest.mark.unit
async def test_cache_does_not_store_failures() -> None:
    cache = TTLCache(ttl_seconds=60)

    async def fail() -> str:
        raise ProviderError("down")

    async def succeed() -> str:
        return "up"

    with pytest.raises(ProviderError):
        await cache.get_or_load("k", fail)
    assert await cache.get_or_load("k", succeed) == "up"
