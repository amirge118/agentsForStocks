"""
Check that everything works, end to end: keys and connectivity (preflight), then
every agent on a few symbols, then a report of the results. From backend/:

    python -m scripts.verify                      # the watchlist
    python -m scripts.verify AAPL NVDA JPM XOM JNJ
    python -m scripts.verify AAPL --force         # run again even if done today
    python -m scripts.verify --json report.json   # also save the report (compare runs)

Exit code: 0 PASS, 1 WARN (results need review), 2 FAIL (or not ready).
With Docker: sh infra/deploy/verify.sh [same arguments].
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.container import build_container
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.ops.preflight import ready, run_preflight
from app.ops.preflight import render as render_preflight
from app.ops.verify import build_report, render
from app.repositories.watchlist import WatchlistRepository

_EXIT = {"PASS": 0, "WARN": 1, "FAIL": 2}


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("symbols", nargs="*", help="default: the watchlist")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", type=Path, help="also write the report here")
    args = parser.parse_args(argv)

    container = build_container(settings, AsyncSessionLocal)
    try:
        checks = await run_preflight(settings, container, AsyncSessionLocal)
        sys.stdout.write("Preflight\n" + render_preflight(checks) + "\n\n")
        if not ready(checks):
            return _EXIT["FAIL"]
        symbols = [s.upper() for s in args.symbols]
        if not symbols:
            async with AsyncSessionLocal() as session:
                symbols = await WatchlistRepository(session).symbols()
        sys.stdout.write(f"Running every agent on {', '.join(symbols)} (a few minutes)...\n\n")
        run = await container.orchestrator.run(symbols, force=args.force)
        report = await build_report(AsyncSessionLocal, container.registry, run, symbols)
    finally:
        await container.aclose()
    sys.stdout.write(render(report) + "\n")
    if args.json:
        args.json.write_text(report.to_json(), encoding="utf-8")
    return _EXIT[report.verdict]


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, "WARNING")
    sys.exit(asyncio.run(main(sys.argv[1:])))
