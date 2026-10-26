"""
Export real prompts from the LLM ledger as an eval dataset (one JSON per line).
Add an "expected" list to a line to make it a labelled case. From backend/:

    python -m evals.capture --days 7 [--agents moat risk] [--per-prompt 20]
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
from app.models.llm_call import LLMCall

DEFAULT_OUT = Path(__file__).parent / "datasets" / "ledger.jsonl"


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
        rows.append(
            {
                "call_id": call.call_id,
                "agent": call.agent,
                "prompt_name": call.prompt_name,
                "model": call.model,
                "system_prompt": call.system_prompt,
                "prompt": call.prompt,
                "response": call.response,
                "expected": None,
            }
        )
    return rows


def write_jsonl(out: Path, rows: list[dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


async def main(argv: list[str]) -> int:
    from app.db.session import AsyncSessionLocal

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--agents", nargs="+", default=None)
    parser.add_argument("--per-prompt", type=int, default=20)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    rows = await capture(
        AsyncSessionLocal, days=args.days, agents=args.agents, per_prompt=args.per_prompt
    )
    out = Path(args.out)
    await asyncio.to_thread(write_jsonl, out, rows)  # file I/O off the event loop
    sys.stdout.write(f"Wrote {len(rows)} cases to {out}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main(sys.argv[1:])))
