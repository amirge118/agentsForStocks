"""
Print LLM token usage and cost from the llm_calls ledger. From backend/:

    python -m scripts.token_report                 # last 7 days, by agent
    python -m scripts.token_report --days 30 --by model
    python -m scripts.token_report --by prompt_version
    python -m scripts.token_report --by provider        # free tiers vs Claude
"""

import argparse
import asyncio
import sys
from datetime import timedelta

from app.core.clock import utcnow
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.ops.token_report import render_usage
from app.repositories.llm_calls import GROUP_BY, LLMCallRepository


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--by", choices=GROUP_BY, default="agent")
    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as session:
        rows = await LLMCallRepository(session).usage(
            since=utcnow() - timedelta(days=args.days), group_by=args.by
        )
    sys.stdout.write(render_usage(rows, args.by, args.days) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
