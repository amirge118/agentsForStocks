"""
Run the pipeline once, now, and print a report. From backend/:

    python -m scripts.run_pipeline AAPL MSFT            # every agent
    python -m scripts.run_pipeline AAPL --agents technicals valuation
    python -m scripts.run_pipeline AAPL --force         # re-run even if done today
    python -m scripts.run_pipeline AAPL --date 2026-06-15   # as of a past day

A past --date is a historical run: every agent sees only what was known that day
(app/providers/point_in_time.py). Its results are stored under that date, so point
DATABASE_URL at a separate database for backtests rather than the live one.

Run `python -m scripts.preflight` first.
"""

import argparse
import asyncio
import sys
from datetime import date

from app.container import build_container
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.observability.telemetry import configure_telemetry
from app.ops.manual_run import render_report


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--agents", nargs="+", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--date", type=date.fromisoformat, help="run as of this past day")
    args = parser.parse_args(argv)

    container = build_container(settings, AsyncSessionLocal)
    try:
        report = await container.orchestrator.run(
            args.symbols, agents=args.agents, force=args.force, run_date=args.date
        )
    finally:
        await container.aclose()
    sys.stdout.write(render_report(report) + "\n")
    return 1 if report.failed else 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    telemetry = configure_telemetry(settings, service_name="agentsforstocks-cli")
    try:
        code = asyncio.run(main(sys.argv[1:]))
    finally:
        telemetry.shutdown()  # flush the run's traces before exiting
    sys.exit(code)
