from datetime import UTC, datetime

import pytest

from app.llm.quota import ProviderQuota, QuotaLimits, estimate_tokens


class Clock:
    """Monotonic seconds, wall time and sleep, all under the test's control."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.wall = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.wall

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def _quota(clock: Clock, limits: QuotaLimits, max_wait: float = 5.0, **kw) -> ProviderQuota:
    return ProviderQuota(
        "free",
        limits,
        max_wait_seconds=max_wait,
        monotonic=clock.monotonic,
        now=clock.now,
        sleep=clock.sleep,
        **kw,
    )


@pytest.mark.unit
def test_estimate_counts_text_and_the_whole_output_budget() -> None:
    assert estimate_tokens("s" * 400, "p" * 4000, 512) == 1100 + 512


@pytest.mark.unit
async def test_requests_per_minute_wait_briefly_then_skip() -> None:
    clock = Clock()
    quota = _quota(clock, QuotaLimits(rpm=2), max_wait=5.0)
    assert await quota.acquire(10) and await quota.acquire(10)
    # The window is full for another 60 s: far longer than the 5 s we may wait
    assert await quota.acquire(10) is None
    clock.t += 57  # 3 s left on the oldest slot → wait it out
    assert await quota.acquire(10) is not None
    assert clock.slept == [pytest.approx(3.0)]


@pytest.mark.unit
async def test_tokens_per_minute_and_oversized_requests() -> None:
    clock = Clock()
    quota = _quota(clock, QuotaLimits(tpm=6_000))
    assert await quota.acquire(7_000) is None  # can never fit
    assert await quota.acquire(4_000)
    assert await quota.acquire(3_000) is None  # 7,000 > 6,000 until the first ages out
    clock.t += 58
    assert await quota.acquire(3_000)
    assert clock.slept == [pytest.approx(2.0)]


@pytest.mark.unit
async def test_settle_replaces_the_estimate_with_real_usage() -> None:
    clock = Clock()
    quota = _quota(clock, QuotaLimits(tpm=6_000, tpd=10_000))
    slot = await quota.acquire(5_000)
    assert slot is not None
    quota.settle(slot, 1_200)  # the reply was much shorter than its budget
    assert quota.day_tokens == 1_200
    assert await quota.acquire(4_000)  # room again in the minute window


@pytest.mark.unit
async def test_daily_limits_reset_at_midnight_in_the_provider_time_zone() -> None:
    clock = Clock()  # 15:00 UTC = 08:00 in Los Angeles
    quota = _quota(clock, QuotaLimits(rpd=2, reset_tz="America/Los_Angeles"))
    assert await quota.acquire(10) and await quota.acquire(10)
    assert await quota.acquire(10) is None
    clock.wall = datetime(2026, 10, 27, 6, 59, tzinfo=UTC)  # 23:59 the same day in LA
    assert await quota.acquire(10) is None
    clock.wall = datetime(2026, 10, 27, 7, 1, tzinfo=UTC)  # 00:01 next day in LA
    assert await quota.acquire(10) is not None
    assert quota.day_requests == 1


@pytest.mark.unit
async def test_tokens_per_day() -> None:
    quota = _quota(Clock(), QuotaLimits(tpd=1_000))
    assert await quota.acquire(800)
    assert await quota.acquire(300) is None


@pytest.mark.unit
async def test_cool_down_after_a_429() -> None:
    clock = Clock()
    quota = _quota(clock, QuotaLimits(rpm=30))
    quota.cool_down(30)
    assert await quota.acquire(10) is None
    clock.t += 27
    assert await quota.acquire(10) is not None
    assert clock.slept == [pytest.approx(3.0)]


@pytest.mark.unit
async def test_the_day_is_seeded_from_the_ledger_once() -> None:
    seen: list[tuple[str, datetime]] = []

    async def load(provider: str, since: datetime) -> tuple[int, int]:
        seen.append((provider, since))
        return 999, 50_000

    quota = _quota(Clock(), QuotaLimits(rpd=1_000, reset_tz="America/Los_Angeles"), load_usage=load)
    assert await quota.acquire(10)
    assert await quota.acquire(10) is None  # 999 used before this process started
    (provider, since), *_ = seen
    assert len(seen) == 1 and provider == "free"
    assert since.isoformat() == "2026-10-26T00:00:00-07:00"


@pytest.mark.unit
async def test_a_broken_ledger_does_not_block_calls() -> None:
    async def load(provider: str, since: datetime) -> tuple[int, int]:
        raise RuntimeError("db down")

    quota = _quota(Clock(), QuotaLimits(rpd=5), load_usage=load)
    assert await quota.acquire(10) is not None
