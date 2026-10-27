"""
Replay the stored analyst calls with other recommendation weights and thresholds and
score each configuration against the settled outcomes. No model calls. From backend/:

    python -m scripts.backtest_weights                 # 20 trading days
    python -m scripts.backtest_weights --horizon 5 --since 2026-09-01 --top 15
"""

import argparse
import asyncio
import sys
from datetime import date

from app.agents.catalog import load_agents
from app.api.v1.endpoints.outcomes import NOT_SCORED
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.domain.backtest import FIT_SHARE, cases_from_calls, run
from app.domain.outcomes import HORIZONS, REVIEW_HORIZON
from app.ops.backtest import render_backtest
from app.repositories.decision_outcomes import DecisionOutcomeRepository


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--horizon", type=int, choices=HORIZONS, default=REVIEW_HORIZON)
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--fit-share", type=float, default=FIT_SHARE)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as session:
        calls = await DecisionOutcomeRepository(session).scored_calls(
            args.horizon, exclude_agents=NOT_SCORED, since=args.since
        )
    results, llm = run(cases_from_calls(calls), load_agents().weights(), args.fit_share)
    sys.stdout.write(render_backtest(results, llm, args.horizon, args.top) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
