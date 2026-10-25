"""
Check keys and connectivity before a real run. From backend/:

    python -m scripts.preflight          # exit code 0 = ready, 1 = not ready
"""

import asyncio
import logging
import sys

from app.container import build_container
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.ops.preflight import ready, render, run_preflight

logger = logging.getLogger(__name__)


async def main() -> int:
    container = build_container(settings, AsyncSessionLocal)
    try:
        results = await run_preflight(settings, container, AsyncSessionLocal)
    finally:
        await container.aclose()
    sys.stdout.write(render(results) + "\n")
    return 0 if ready(results) else 1


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, "WARNING")
    sys.exit(asyncio.run(main()))
