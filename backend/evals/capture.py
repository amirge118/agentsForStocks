"""
Export real prompts from the LLM ledger as an eval dataset (one JSON per line).
Add an "expected" list to a line to make it a labelled case. From backend/:

    python -m evals.capture --days 7 [--agents moat risk] [--per-prompt 20]

With --outcomes, only calls whose decision has a settled outcome are exported,
each with that outcome (alpha vs the benchmark), for `evals.run --suite outcomes`:

    python -m evals.capture --outcomes [--horizon 20] [--days 90]
"""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import utcnow
from app.domain.outcomes import REVIEW_HORIZON
from app.models.agent_run import AgentRun
from app.models.decision_outcome import DecisionOutcome
from app.models.llm_call import LLMCall

DEFAULT_OUT = Path(__file__).parent / "datasets" / "ledger.jsonl"
OUTCOMES_OUT = Path(__file__).parent / "datasets" / "outcomes.jsonl"


async def capture(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int,
    agents: list[str] | None,
    per_prompt: int,
) -> list[dict]:
    stmt = (
        select(LLMCall)
        .where(
            LLMCall.created_at >= utcnow() - timedelta(days=days),
            LLMCall.status == "ok",
            LLMCall.prompt.is_not(None),
            LLMCall.agent.is_not(None),
        )
        .order_by(LLMCall.created_at.desc())
    )
    if agents:
        stmt = stmt.where(LLMCall.agent.in_(agents))
    async with session_factory() as session:
        calls = (await session.execute(stmt)).scalars().all()
    rows: list[dict] = []
    taken: dict[str, int] = {}
    for call in calls:
        key = call.prompt_name or call.agent or ""
        if taken.get(key, 0) >= per_prompt:
            continue
        taken[key] = taken.get(key, 0) + 1
        rows.append(_row(call))
    return rows


async def capture_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int,
    agents: list[str] | None,
    horizon: int = REVIEW_HORIZON,
) -> list[dict]:
    """
    Calls whose (symbol, run date) has a settled outcome at `horizon`: the prompt
    holds exactly what the agent saw that day, the outcome is what followed —
    so replaying it scores a configuration against reality with no look-ahead.
    """
    stmt = (
        select(LLMCall, DecisionOutcome)
        .join(AgentRun, AgentRun.run_id == LLMCall.run_id)
        .join(
            DecisionOutcome,
            (DecisionOutcome.symbol == AgentRun.symbol)
            & (DecisionOutcome.decision_date == AgentRun.run_date),
        )
        .where(
            LLMCall.created_at >= utcnow() - timedelta(days=days),
            LLMCall.status == "ok",
            LLMCall.prompt.is_not(None),
            LLMCall.agent.in_(agents or ["recommendation"]),
            DecisionOutcome.horizon_days == horizon,
            DecisionOutcome.status == "settled",
        )
        .order_by(LLMCall.created_at.desc())
    )
    async with session_factory() as session:
        found = (await session.execute(stmt)).all()
    return [
        {
            **_row(call),
            "outcome": {
                "symbol": outcome.symbol,
                "decision_date": outcome.decision_date.isoformat(),
                "horizon": outcome.horizon_days,
                "benchmark": outcome.benchmark,
                "raw_return": outcome.raw_return,
                "alpha": outcome.alpha,
            },
        }
        for call, outcome in found
    ]


def _row(call: LLMCall) -> dict:
    return {
        "call_id": call.call_id,
        "agent": call.agent,
        "prompt_name": call.prompt_name,
        "model": call.model,
        "system_prompt": call.system_prompt,
        "prompt": call.prompt,
        "response": call.response,
        "expected": None,
    }


def write_jsonl(out: Path, rows: list[dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


async def main(argv: list[str]) -> int:
    from app.db.session import AsyncSessionLocal

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--agents", nargs="+", default=None)
    parser.add_argument("--per-prompt", type=int, default=20)
    parser.add_argument("--outcomes", action="store_true", help="only calls with a settled outcome")
    parser.add_argument("--horizon", type=int, default=REVIEW_HORIZON)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.outcomes:
        rows = await capture_outcomes(
            AsyncSessionLocal, days=args.days, agents=args.agents, horizon=args.horizon
        )
    else:
        rows = await capture(
            AsyncSessionLocal, days=args.days, agents=args.agents, per_prompt=args.per_prompt
        )
    out = Path(args.out or (OUTCOMES_OUT if args.outcomes else DEFAULT_OUT))
    await asyncio.to_thread(write_jsonl, out, rows)  # file I/O off the event loop
    sys.stdout.write(f"Wrote {len(rows)} cases to {out}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main(sys.argv[1:])))
