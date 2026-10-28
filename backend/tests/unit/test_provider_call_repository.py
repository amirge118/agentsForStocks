from datetime import date

import pytest

from app.repositories.provider_calls import ProviderCallRepository, StoredCallCounter


@pytest.mark.unit
async def test_increment_counts_per_provider_and_day(db_session) -> None:
    repo = ProviderCallRepository(db_session)
    day = date(2026, 10, 28)
    assert [await repo.increment("fmp", day) for _ in range(3)] == [1, 2, 3]
    assert await repo.increment("fmp", date(2026, 10, 29)) == 1
    assert await repo.increment("other", day) == 1
    assert await repo.count("fmp", day) == 3
    assert await repo.count("fmp", date(2026, 1, 1)) == 0


@pytest.mark.unit
async def test_stored_counter_commits_each_call(session_factory, db_session) -> None:
    counter = StoredCallCounter(session_factory, "fmp")
    day = date(2026, 10, 28)
    assert await counter.increment(day) == 1
    assert await counter.increment(day) == 2
    assert await ProviderCallRepository(db_session).count("fmp", day) == 2
