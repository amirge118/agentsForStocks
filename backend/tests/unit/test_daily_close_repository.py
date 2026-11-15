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
