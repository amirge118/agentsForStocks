"""
Print each agent's track record from the settled outcomes. From backend/:

    python -m scripts.track_report                  # 20 trading days, all history
    python -m scripts.track_report --horizon 5 --since 2026-09-01
"""

import argparse
import asyncio
import sys
from datetime import date

from app.api.v1.endpoints.outcomes import NOT_SCORED
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.domain.outcomes import HORIZONS, REVIEW_HORIZON, agent_tracks
from app.ops.track_report import render_track_record
from app.repositories.decision_outcomes import DecisionOutcomeRepository


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--horizon", type=int, choices=HORIZONS, default=REVIEW_HORIZON)
    parser.add_argument("--since", type=date.fromisoformat)
    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as session:
        repo = DecisionOutcomeRepository(session)
        calls = await repo.scored_calls(args.horizon, exclude_agents=NOT_SCORED, since=args.since)
        pending = (await repo.status_counts(args.horizon)).get("pending", 0)
    sys.stdout.write(render_track_record(agent_tracks(calls), args.horizon, pending) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
