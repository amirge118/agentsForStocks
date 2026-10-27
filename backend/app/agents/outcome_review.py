"""
OutcomeReviewAgent — turns settled recommendations into short lessons for later runs.

Each day, per symbol: the recommendations whose 20-session outcome is now known
(settled by app/pipeline/settlement.py, exit before the run date) and that no
earlier review covered — at most REVIEW_LIMIT, oldest first — each get one model
call: what the alpha says about the call, which part of the reasoning held, one
lesson. The lessons are this agent's stored result, so they get what every agent
run gets (idempotency, agent_runs, the LLM ledger, compliance, profiles), and the
recommendation agent reads them back point-in-time through ctx.outcomes.

Signal is always neutral with 0% confidence: this agent judges past calls, not
the stock (recommendation weight 0).
"""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import Agent, AnalysisResult
from app.agents.registry import register_agent
from app.domain.outcomes import REVIEW_HORIZON, Lesson, SettledCall, hold_band
from app.domain.signals import SignalLabel
from app.knowledge.store import Learning
from app.repositories.agent_results import AgentResultRepository
from app.repositories.decision_outcomes import DecisionOutcomeRepository

AGENT = "outcome_review"
REVIEWED_AGENT = "recommendation"
# Lessons per run: a backlog (the first weeks of history) is worked off a few a day
REVIEW_LIMIT = 3
# How far back to look for settled calls nobody reviewed yet
LOOKBACK = 30


class LessonReply(BaseModel):
    lesson: str = Field(description="2-4 plain sentences: what the alpha shows, why, one lesson")


class LessonView(BaseModel):
    decision_date: date
    signal: SignalLabel
    confidence: float
    horizon_days: int
    benchmark: str
    raw_return: float
    alpha: float
    hit: bool
    text: str


class OutcomeReviewResult(AnalysisResult):
    lessons: list[LessonView]


class ReviewBacklog:
    """
    The settled calls still to review, oldest first. Deliberately not a dataclass:
    contracts treat an empty dataclass field as a missing input, but an empty
    backlog is a quiet day, not missing data.
    """

    def __init__(self, calls: Sequence[SettledCall]) -> None:
        self.calls = tuple(calls)


def _signed(fraction: float) -> str:
    return f"{fraction * 100:+.1f}%"


def _lessons_cite_alpha(data: ReviewBacklog, result: OutcomeReviewResult) -> str | None:
    """The prompt asks each lesson to quote its alpha; one that doesn't may misstate it."""
    uncited = [
        str(lesson.decision_date)
        for lesson in result.lessons
        if f"{abs(lesson.alpha) * 100:.1f}%" not in lesson.text
    ]
    return f"lessons that don't quote their alpha: {', '.join(uncited)}" if uncited else None


@register_agent(
    AGENT,
    description="Lessons from settled recommendations (20 trading days vs benchmark)",
    invariants=(_lessons_cite_alpha,),
)
class OutcomeReviewAgent(Agent[ReviewBacklog, OutcomeReviewResult]):
    result_model = OutcomeReviewResult

    async def fetch(self, symbol: str, run_date: date) -> ReviewBacklog:
        calls = await self.ctx.outcomes.settled_calls(
            symbol, agent=REVIEWED_AGENT, horizon=REVIEW_HORIZON, before=run_date, limit=LOOKBACK
        )
        # Reviews from earlier days only: a forced rerun today reviews the same calls again
        earlier = await self.ctx.outcomes.lessons(
            until=run_date - timedelta(days=1), symbol=symbol, limit=LOOKBACK * REVIEW_LIMIT
        )
        reviewed = {lesson.decision_date for lesson in earlier}
        todo = sorted(
            (c for c in calls if c.decision_date not in reviewed), key=lambda c: c.decision_date
        )
        return ReviewBacklog(todo[:REVIEW_LIMIT])

    async def analyze(
        self, symbol: str, data: ReviewBacklog, memory: list[str]
    ) -> OutcomeReviewResult:
        lessons = [await self._review(call) for call in data.calls]
        if lessons:
            hits = sum(1 for lesson in lessons if lesson.hit)
            calls = "; ".join(
                f"{lesson.decision_date} {lesson.signal} {_signed(lesson.alpha)}"
                for lesson in lessons
            )
            noun = "call" if len(lessons) == 1 else "calls"
            reasoning = f"Reviewed {len(lessons)} settled {noun}, {hits} right: {calls}"
        else:
            reasoning = "No newly settled recommendations to review"
        return OutcomeReviewResult(
            signal="neutral",
            confidence=0.0,
            reasoning=reasoning,
            summary=f"Outcome review: {reasoning}",
            lessons=lessons,
        )

    def learnings(self, symbol: str, result: OutcomeReviewResult) -> list[Learning]:
        return [
            Learning(
                kind="pattern",
                content=f"{symbol} {lesson.decision_date} {lesson.signal} call, "
                f"alpha {_signed(lesson.alpha)}: {lesson.text}",
                tags=("lesson",),
            )
            for lesson in result.lessons
        ]

    async def _review(self, call: SettledCall) -> LessonView:
        fallback = LessonReply(
            lesson=f"Alpha {_signed(call.alpha)} vs {call.benchmark} over {call.horizon} "
            f"trading days; the {call.signal} call was {'right' if call.hit else 'wrong'}."
        )
        reply = await self.ask(_prompt(call), schema=LessonReply, fallback=fallback, max_tokens=400)
        return LessonView(
            decision_date=call.decision_date,
            signal=call.signal,
            confidence=call.confidence,
            horizon_days=call.horizon,
            benchmark=call.benchmark,
            raw_return=call.raw_return,
            alpha=call.alpha,
            hit=call.hit,
            text=reply.lesson.strip(),
        )


def _rule(signal: str, horizon: int) -> str:
    if signal == "bullish":
        return "a bullish call needs positive alpha"
    if signal == "bearish":
        return "a bearish call needs negative alpha"
    return f"a neutral call needs alpha within ±{hold_band(horizon) * 100:.1f}%"


def _prompt(call: SettledCall) -> str:
    benchmark_return = call.raw_return - call.alpha
    return f"""Symbol: {call.symbol}
Recommendation on {call.decision_date}: {call.signal} ({call.confidence:.0f}%)
Reasoning at the time: {call.reasoning or 'not recorded'}

Outcome over {call.horizon} trading days (first close after {call.decision_date} to \
{call.exit_date}):
Stock return: {_signed(call.raw_return)}
Benchmark ({call.benchmark}) return: {_signed(benchmark_return)}
Alpha: {_signed(call.alpha)}
Verdict by the system's rule ({_rule(call.signal, call.horizon)}): \
{'right' if call.hit else 'wrong'}"""


class SessionOutcomesReader:
    """OutcomesReader backed by short-lived sessions: settled outcomes and stored lessons."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def settled_calls(
        self, symbol: str, *, agent: str, horizon: int, before: date, limit: int
    ) -> list[SettledCall]:
        async with self._session_factory() as session:
            return await DecisionOutcomeRepository(session).settled_calls(
                symbol, agent=agent, horizon=horizon, before=before, limit=limit
            )

    async def lessons(
        self,
        *,
        until: date,
        symbol: str | None = None,
        exclude_symbol: str | None = None,
        limit: int = 5,
    ) -> list[Lesson]:
        """Newest first. A review dated `until` only read outcomes closed before it."""
        async with self._session_factory() as session:
            rows = await AgentResultRepository(session).recent(
                AGENT, until=until, symbol=symbol, exclude_symbol=exclude_symbol, limit=limit
            )
        lessons = [
            lesson
            for row in rows
            for lesson in sorted(
                _parse_lessons(row.symbol, row.result_json),
                key=lambda lesson: lesson.decision_date,
                reverse=True,
            )
        ]
        return lessons[:limit]


def _parse_lessons(symbol: str, result: dict[str, Any]) -> list[Lesson]:
    return [
        Lesson(
            symbol=symbol,
            decision_date=date.fromisoformat(str(item["decision_date"])),
            signal=str(item["signal"]),
            alpha=float(item["alpha"]),
            text=str(item["text"]),
        )
        for item in result.get("lessons", [])
    ]
