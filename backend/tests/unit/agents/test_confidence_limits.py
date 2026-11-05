from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from app.agents.contracts import cap_confidence, when_missing
from app.agents.growth import GrowthResult
from app.agents.institutional import _format_holders
from app.agents.registry import registry
from app.agents.runner import AgentRunner
from app.agents.valuation import ValuationResult
from app.domain.valuation import cash_flow_dcf_fits
from app.knowledge.store import NullKnowledgeStore
from app.models.agent_result import AgentResult
from tests.factories import FakeLLM, make_context

DAY = date(2026, 8, 3)


def _growth(confidence: float, gaps: list[str]) -> GrowthResult:
    return GrowthResult(
        signal="bullish",
        confidence=confidence,
        reasoning="r",
        summary=f"Growth: bullish ({confidence:.0f}%) — r",
        data_gaps=gaps,
        transcript_available=False,
        analyst_coverage=0,
    )


def _valuation(confidence: float, margin: float, intrinsic: float = 1e9, fits: bool = True):
    return ValuationResult(
        signal="bullish",
        confidence=confidence,
        reasoning="r",
        summary=f"Valuation: bullish ({confidence:.0f}%) — r",
        dcf={},
        earnings_power_value=None,
        ev_ebitda_value=None,
        avg_intrinsic_value=intrinsic,
        margin_of_safety=margin,
        market_cap=1e9,
        growth_rate=0.1,
        growth_source="s",
        discount_rate=0.1,
        implied_growth=None,
        cash_flow_dcf_fits=fits,
    )


@pytest.mark.unit
def test_a_ceiling_lowers_the_result_and_says_why() -> None:
    capped = cap_confidence(_growth(95, ["estimates"]), (when_missing("estimates", 60),))
    assert capped.confidence == 60
    assert capped.summary.startswith("Growth: bullish (60%)")
    assert capped.contract_violations == ["95% confidence lowered to 60%: no estimates"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("confidence", "gaps"), [(55.0, ["estimates"]), (95.0, []), (95.0, ["income"])]
)
def test_a_result_within_its_ceiling_is_untouched(confidence: float, gaps: list[str]) -> None:
    result = _growth(confidence, gaps)
    assert cap_confidence(result, (when_missing("estimates", 60),)) == result


@pytest.mark.unit
def test_capping_twice_changes_nothing_more() -> None:
    limits = (when_missing("estimates", 60),)
    once = cap_confidence(_growth(95, ["estimates"]), limits)
    assert cap_confidence(once, limits) == once


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "ceiling"),
    [
        (_valuation(90, 2.76), 50),  # implausibly wide: PGY, 2026-11
        (_valuation(85, 0.70, fits=False), 50),  # an insurer: OSCR, 2026-11
        (_valuation(80, 0.0, intrinsic=0.0), 25),  # nothing to compare: IONQ, 2026-11
        (_valuation(85, 0.21), 85),  # a sound model keeps its confidence
    ],
)
def test_valuation_limits(result: ValuationResult, ceiling: float) -> None:
    limits = registry.get("valuation").agent_cls.confidence_limits
    assert cap_confidence(result, limits).confidence == ceiling


@pytest.mark.unit
@pytest.mark.parametrize(
    ("info", "fits"),
    [
        ({"sector": "Healthcare", "industry": "Healthcare Plans"}, False),
        ({"sector": "Financial Services", "industry": "Asset Management"}, False),
        ({"sector": "Technology", "industry": "Software - Infrastructure"}, True),
        ({}, True),
    ],
)
def test_where_a_cash_flow_dcf_fits(info: dict, fits: bool) -> None:
    assert cash_flow_dcf_fits(info) is fits


@pytest.mark.unit
def test_an_unknown_holder_change_is_not_shown_as_zero() -> None:
    table = _format_holders([{"holder": "Vanguard", "shares": 50.0}])
    assert table.endswith("| N/A")


@pytest.mark.unit
async def test_a_reused_result_from_before_the_limits_is_capped_too(session_factory) -> None:
    agent = registry.get("growth").agent_cls(make_context(llm=FakeLLM()))
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    await runner.run(agent, "AAPL", DAY)
    async with session_factory() as session:
        stored = await session.scalar(select(AgentResult))
        old = _growth(90, ["estimates"]).model_dump(mode="json")
        await session.execute(
            update(AgentResult).where(AgentResult.id == stored.id).values(result_json=old)
        )
        await session.commit()

    outcome = await runner.run(agent, "AAPL", DAY + timedelta(days=1))

    assert outcome.status == "reused"
    assert outcome.result is not None and outcome.result.confidence == 60
    async with session_factory() as session:
        rows = await session.scalars(select(AgentResult).order_by(AgentResult.run_date))
        assert [r.result_json["confidence"] for r in rows] == [90, 60]
