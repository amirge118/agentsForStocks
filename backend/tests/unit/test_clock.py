from datetime import UTC, date, datetime

import pytest

from app.core.clock import market_close, market_today, utcnow


@pytest.mark.unit
def test_market_today_uses_new_york_date_not_utc() -> None:
    # 02:00 UTC on Mar 25 is still 22:00 ET on Mar 24
    late_evening_et = datetime(2026, 3, 25, 2, 0, tzinfo=UTC)
    assert market_today(late_evening_et) == date(2026, 3, 24)


@pytest.mark.unit
def test_utcnow_is_timezone_aware() -> None:
    assert utcnow().tzinfo is not None


@pytest.mark.unit
def test_market_close_follows_daylight_saving() -> None:
    assert market_close(date(2026, 7, 1)).astimezone(UTC).hour == 20
    assert market_close(date(2026, 12, 1)).astimezone(UTC).hour == 21
