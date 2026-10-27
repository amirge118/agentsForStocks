"""
Settle past decisions against realised prices (what the daily job does before the
agents). From backend/:

    python -m scripts.settle_outcomes                    # every symbol, as of today
    python -m scripts.settle_outcomes --symbols AAPL MSFT
    python -m scripts.settle_outcomes --as-of 2026-10-01 # only windows closed before then
"""

import argparse
import asyncio
import sys
from datetime import date

from app.container import build_container
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.symbols import validate_symbol
from app.db.session import AsyncSessionLocal


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--symbols", nargs="+", type=validate_symbol)
    parser.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)

    container = build_container(settings, AsyncSessionLocal)
    try:
        report = await container.settler.settle(as_of=args.as_of, symbols=args.symbols)
    finally:
        await container.aclose()
    sys.stdout.write(report.render() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
