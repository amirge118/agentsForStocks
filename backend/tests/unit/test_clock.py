from datetime import UTC, date, datetime

import pytest

from app.core.clock import market_close, market_is_open, market_today, utcnow


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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("moment", "is_open"),
    [
        (datetime(2026, 11, 16, 14, 30, tzinfo=UTC), True),  # Monday 09:30 ET
        (datetime(2026, 11, 16, 14, 29, tzinfo=UTC), False),  # a minute before
        (datetime(2026, 11, 16, 20, 59, tzinfo=UTC), True),  # 15:59 ET
        (datetime(2026, 11, 16, 21, 0, tzinfo=UTC), False),  # the close
        (datetime(2026, 11, 15, 16, 0, tzinfo=UTC), False),  # Sunday
    ],
)
def test_market_is_open_on_weekdays_between_the_open_and_the_close(
    moment: datetime, is_open: bool
) -> None:
    assert market_is_open(moment) is is_open
