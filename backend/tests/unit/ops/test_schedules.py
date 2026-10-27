from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.ops.schedules import render_schedules

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


@pytest.mark.unit
def test_off_by_default_lists_jobs_without_next_runs() -> None:
    out = render_schedules(Settings(), NOW)
    assert "OFF (SCHEDULER_ENABLED=false)" in out
    assert "daily_pipeline" in out and "30 18 * * mon-fri" in out
    assert "2026-10-26" not in out  # nothing will run
    assert "Dependabot" in out and "CI" in out


@pytest.mark.unit
def test_on_shows_where_it_runs_and_next_runs() -> None:
    out = render_schedules(
        Settings(scheduler_enabled=True, run_scheduler=False, maintenance_schedule=""), NOW
    )
    assert "python -m app.worker" in out
    assert "Mon 2026-10-26 18:30" in out
    assert "(off)" in out  # maintenance turned off by an empty schedule
    assert "in the API process" in render_schedules(Settings(scheduler_enabled=True), NOW)
