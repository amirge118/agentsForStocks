"""
Compliance review of results stored before the per-agent gate existed (they have
no `compliance` field): each one is reviewed now and updated in place, so the
API, the breakdown and the knowledge base never show unreviewed reasoning.
Idempotent — a reviewed result is left alone.
"""

import logging
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.compliance import review_stored
from app.repositories.agent_results import AgentResultRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillReport:
    scanned: int
    statuses: dict[str, int]  # pass / flag / fail among the newly reviewed
    dry_run: bool

    def render(self) -> str:
        reviewed = sum(self.statuses.values())
        verb = "would review" if self.dry_run else "reviewed"
        parts = ", ".join(f"{k} {v}" for k, v in sorted(self.statuses.items())) or "none"
        return f"{self.scanned} stored results, {verb} {reviewed} ({parts})"


async def backfill_compliance(
    session_factory: async_sessionmaker[AsyncSession], *, dry_run: bool = False
) -> BackfillReport:
    statuses: Counter[str] = Counter()
    async with session_factory() as session:
        rows = await AgentResultRepository(session).all()
        for row in rows:
            reviewed = review_stored(row.agent_type, row.symbol, row.result_json)
            if reviewed is None:
                continue
            statuses[reviewed["compliance"]["status"]] += 1
            if not dry_run:
                row.result_json = reviewed  # a new object, so the JSON column is saved
        if not dry_run:
            await session.commit()
    report = BackfillReport(len(rows), dict(statuses), dry_run)
    logger.info("Compliance backfill: %s", report.render())
    return report
