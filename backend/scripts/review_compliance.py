"""
Review stored results that predate the per-agent compliance gate. From backend/:

    python -m scripts.review_compliance --dry-run   # count what would change
    python -m scripts.review_compliance
"""

import argparse
import asyncio
import sys

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.ops.compliance_backfill import backfill_compliance


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = await backfill_compliance(AsyncSessionLocal, dry_run=args.dry_run)
    sys.stdout.write(report.render() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
