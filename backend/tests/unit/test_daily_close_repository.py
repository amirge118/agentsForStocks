from datetime import date
from decimal import Decimal

import pytest

from app.repositories.daily_closes import DailyCloseRepository


@pytest.mark.unit
async def test_a_close_is_stored_once_and_the_latest_comes_back(db_session) -> None:
    repo = DailyCloseRepository(db_session)
    first = [(date(2026, 11, 12), 523.0), (date(2026, 11, 13), 523.880005)]
    assert await repo.save("MSFT", first) == 2
    assert await repo.save("MSFT", [*first, (date(2026, 11, 16), 530.1)]) == 1
    assert await repo.save("SPY", []) == 0
    await repo.save("SPY", [(date(2026, 11, 13), 754.37)])
    await db_session.commit()

    latest = await repo.latest(["MSFT", "SPY", "NONE"])
    assert latest == {
        "MSFT": (date(2026, 11, 16), Decimal("530.1")),
        "SPY": (date(2026, 11, 13), Decimal("754.37")),
    }
    assert await repo.latest([]) == {}


@pytest.mark.unit
async def test_closes_between_two_days_by_symbol(db_session) -> None:
    repo = DailyCloseRepository(db_session)
    await repo.save("MSFT", [(date(2026, 11, d), 500.0 + d) for d in (9, 10, 11, 12)])
    await repo.save("SPY", [(date(2026, 11, 10), 750.0)])
    await db_session.commit()

    got = await repo.between(["MSFT", "SPY", "NONE"], date(2026, 11, 10), date(2026, 11, 11))
    assert got == {
        "MSFT": {date(2026, 11, 10): Decimal("510"), date(2026, 11, 11): Decimal("511")},
        "SPY": {date(2026, 11, 10): Decimal("750")},
    }
    assert await repo.between([], date(2026, 11, 1), date(2026, 11, 30)) == {}
