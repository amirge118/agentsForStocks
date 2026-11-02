"""
Where one agent stands and where to start improving it: configuration, runs,
latest calls, data gaps, contract violations, model calls, track record, eval
coverage. Reads the database only — no model or data-provider calls. From backend/:

    python -m scripts.agent_card recommendation
    python -m scripts.agent_card valuation --days 30

The improvement loop that starts here: docs/agent-improvement-loop.md.
"""

import argparse
import asyncio
import sys
from datetime import timedelta

from app.agents.catalog import load_agents
from app.core.clock import market_today
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.llm.profiles import ProfileBook
from app.ops.agent_card import EvalCoverage, build_card, render_card
from evals import cases as eval_cases


def eval_coverage(agent: str) -> EvalCoverage:
    cases = eval_cases.select(eval_cases.scenario_suite(), [agent])
    return EvalCoverage(len(cases), sum(c.labelled for c in cases))


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("agent")
    parser.add_argument("--days", type=int, default=14, help="window of market days to read")
    args = parser.parse_args(argv)

    today = market_today()
    async with AsyncSessionLocal() as session:
        try:
            card = await build_card(
                session,
                load_agents(),
                args.agent,
                since=today - timedelta(days=args.days),
                today=today,
                profiles=ProfileBook.from_config(
                    settings.agent_profiles, settings.agent_profiles_file
                ),
                evals=eval_coverage(args.agent),
            )
        except KeyError as exc:
            sys.stderr.write(f"{exc.args[0]}\n")
            return 2
    sys.stdout.write(render_card(card) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    configure_logging(settings.log_format, settings.log_level)
    sys.exit(asyncio.run(main(sys.argv[1:])))
