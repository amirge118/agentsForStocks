"""
List every scheduled job: whether the scheduler is on, each job's schedule and
next run. From backend/:

    python -m scripts.schedules
"""

import sys

from app.core.config import settings
from app.ops.schedules import render_schedules

if __name__ == "__main__":  # pragma: no cover
    sys.stdout.write(render_schedules(settings) + "\n")
