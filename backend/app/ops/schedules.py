"""What runs on its own, and when (`python -m scripts.schedules`)."""

from datetime import datetime

from app.agents.scheduler import jobs
from app.core.clock import MARKET_TZ
from app.core.config import Settings

# Schedules outside the app, defined in the repository (they never run the pipeline)
REPO_SCHEDULES = [
    ("CI", ".github/workflows/ci.yml", "on push to main and on pull requests only"),
    ("Dependabot", ".github/dependabot.yml", "weekly (Monday): opens update PRs only"),
]


def render_schedules(settings: Settings, now: datetime | None = None) -> str:
    if not settings.scheduler_enabled:
        state = "OFF (SCHEDULER_ENABLED=false) — no job runs on its own"
    elif settings.run_scheduler:
        state = "ON — in the API process (RUN_SCHEDULER=true)"
    else:
        state = "ON — in `python -m app.worker` only (RUN_SCHEDULER=false on the API)"
    lines = [f"Scheduler: {state}", f"Time zone: {MARKET_TZ}", ""]
    header = f"{'job':<20} {'setting':<21} {'schedule':<18} {'next run':<20} what it does"
    lines += [header, "-" * len(header)]
    for job in jobs(settings):
        next_run = job.next_run(now) if settings.scheduler_enabled else None
        when = next_run.astimezone(MARKET_TZ).strftime("%a %Y-%m-%d %H:%M") if next_run else "—"
        schedule = job.schedule if job.enabled else "(off)"
        lines.append(
            f"{job.job_id:<20} {job.setting:<21} {schedule:<18} {when:<20} {job.description}"
        )
    lines += ["", "Outside the app:"]
    lines += [f"  {name:<11} {path:<26} {what}" for name, path, what in REPO_SCHEDULES]
    return "\n".join(lines)
