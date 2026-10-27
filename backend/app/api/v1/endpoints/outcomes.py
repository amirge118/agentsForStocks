"""
GET /api/v1/outcomes/track-record — how each agent's past calls turned out: hit rate,
alpha captured vs the benchmark, per signal and per confidence bucket, at 5 / 20 / 60
trading sessions (settled by app/pipeline/settlement.py).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.outcome_review import AGENT as OUTCOME_REVIEW
from app.api.deps import get_session
from app.domain.outcomes import HORIZONS, REVIEW_HORIZON, agent_tracks
from app.repositories.decision_outcomes import DecisionOutcomeRepository
from app.schemas.api import AgentTrackRecord, TrackRecordReport

router = APIRouter(prefix="/outcomes", tags=["outcomes"])

# Judges past calls, not the stock: its neutral 0% is not a call to score
NOT_SCORED = (OUTCOME_REVIEW,)


def horizon_param(
    horizon: int = Query(default=REVIEW_HORIZON, description="Trading sessions: 5, 20 or 60"),
) -> int:
    if horizon not in HORIZONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"horizon must be one of {list(HORIZONS)}"
        )
    return horizon


@router.get("/track-record", response_model=TrackRecordReport)
async def track_record(
    horizon: int = Depends(horizon_param),
    since: date | None = Query(default=None, description="Only decisions on or after this day"),
    session: AsyncSession = Depends(get_session),
) -> TrackRecordReport:
    repo = DecisionOutcomeRepository(session)
    calls = await repo.scored_calls(horizon, exclude_agents=NOT_SCORED, since=since)
    counts = await repo.status_counts(horizon)
    return TrackRecordReport(
        horizon=horizon,
        since=since,
        settled=counts.get("settled", 0),
        pending=counts.get("pending", 0),
        unavailable=counts.get("unavailable", 0),
        agents=[AgentTrackRecord.from_track(t) for t in agent_tracks(calls)],
    )
