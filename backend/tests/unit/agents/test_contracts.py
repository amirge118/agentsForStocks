"""
Agent contracts and golden scenarios: every agent, fed company archetypes, must
produce results consistent with its inputs and with the rules its prompt states.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select

from app.agents.base import AnalysisResult
from app.agents.catalog import load_agents
from app.agents.contracts import NO_DATA_MAX_CONFIDENCE, apply_contract, missing_inputs
from app.agents.runner import AgentRunner, SessionResultsReader
from app.knowledge.store import NullKnowledgeStore
from app.models.agent_result import AgentResult
from app.pipeline.orchestrator import PipelineOrchestrator
from tests import scenarios
from tests.factories import FakeLLM, FakeResults, make_context

RUN_DATE = date(2026, 10, 23)
registry = load_agents()


@dataclass(frozen=True)
class _Data:
    text: str
    rows: list
    frame: pd.DataFrame
    info: dict
    count: int = 0  # a number is never "missing"


def _result(signal: str = "bullish", confidence: float = 80) -> AnalysisResult:
    return AnalysisResult(
        signal=signal, confidence=confidence, reasoning="r", summary=f"x ({confidence:.0f}%) — r"
    )


@pytest.mark.unit
def test_missing_inputs_finds_empty_fields() -> None:
    data = _Data(text="  ", rows=[], frame=pd.DataFrame(), info={"a": 1})
    assert missing_inputs(data) == ["text", "rows", "frame"]
    assert missing_inputs({}) == ["data"]
    assert missing_inputs(pd.DataFrame({"a": [1]})) == []
    assert missing_inputs(None) == ["data"]


@pytest.mark.unit
def test_no_input_data_caps_confidence_and_records_the_violation() -> None:
    checked = apply_contract("x", "AAPL", {}, _result(confidence=80), ())
    assert checked.confidence == NO_DATA_MAX_CONFIDENCE
    assert "(25%)" in checked.summary
    assert checked.data_gaps == ["data"]
    assert "no input data" in checked.contract_violations[0]
    # A field that is present (count) means the agent had *some* data: no cap
    some = _Data(text="", rows=[], frame=pd.DataFrame(), info={})
    assert apply_contract("x", "AAPL", some, _result(confidence=80), ()).confidence == 80


@pytest.mark.unit
def test_partial_gaps_and_invariants_are_recorded_without_changing_the_result() -> None:
    data = _Data(text="10-K", rows=[], frame=pd.DataFrame({"a": [1]}), info={"a": 1})
    checked = apply_contract(
        "x", "AAPL", data, _result(), (lambda d, r: "always broken", lambda d, r: None)
    )
    assert (checked.signal, checked.confidence) == ("bullish", 80)
    assert checked.data_gaps == ["rows"]
    assert checked.contract_violations == ["always broken"]


async def _run_agent(name: str, scenario: scenarios.Scenario, llm: FakeLLM, session_factory):
    ctx = make_context(yfinance=scenario.yfinance, fmp=scenario.fmp, edgar=scenario.edgar, llm=llm)
    agent = registry.get(name).agent_cls(ctx)
    runner = AgentRunner(session_factory, NullKnowledgeStore())
    return await runner.run(agent, "AAPL", RUN_DATE, force=True)


@pytest.mark.unit
@pytest.mark.parametrize("scenario", scenarios.ALL, ids=lambda s: s.__name__)
async def test_every_agent_completes_every_scenario(scenario, concurrent_session_factory) -> None:
    ctx = make_context(
        yfinance=scenario().yfinance,
        fmp=scenario().fmp,
        edgar=scenario().edgar,
        llm=FakeLLM(),
        results=SessionResultsReader(concurrent_session_factory),
    )
    orchestrator = PipelineOrchestrator(
        AgentRunner(concurrent_session_factory, NullKnowledgeStore()),
        registry,
        build_agent=lambda name: registry.get(name).agent_cls(ctx),
        today=lambda: RUN_DATE,  # a live run on RUN_DATE, not a historical one
    )
    report = await orchestrator.run(["AAPL"], run_date=RUN_DATE)
    assert report.failed == []
    assert report.counts == {"completed": len(registry.names())}


@pytest.mark.unit
# recommendation: tested below; outcome_review reads no market data (an empty backlog
# is a quiet day, not a data gap — tests/unit/agents/test_outcome_review.py)
@pytest.mark.parametrize(
    "name", [n for n in registry.names() if n not in ("recommendation", "outcome_review")]
)
async def test_no_data_means_gaps_low_confidence_and_a_warned_prompt(
    name: str, session_factory, db_session
) -> None:
    llm = FakeLLM(reply={"signal": "bullish", "confidence": 90.0, "reasoning": "Looks great"})
    outcome = await _run_agent(name, scenarios.no_data(), llm, session_factory)

    assert outcome.status == "completed"
    stored = (await db_session.execute(select(AgentResult))).scalar_one().result_json
    assert stored["data_gaps"], "every input was empty"
    assert stored["confidence"] <= NO_DATA_MAX_CONFIDENCE
    for call in llm.calls:  # Claude is told, so it doesn't judge absent data
        assert "Missing inputs" in call["prompt"]


@pytest.mark.unit
async def test_recommendation_without_analysts_holds_without_calling_the_llm(
    session_factory,
) -> None:
    llm = FakeLLM()
    agent = registry.get("recommendation").agent_cls(make_context(llm=llm, results=FakeResults()))
    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)
    assert outcome.result is not None
    assert (outcome.result.action, outcome.result.confidence) == ("HOLD", 0.0)
    assert outcome.result.data_gaps == ["results"]
    assert llm.calls == []


@pytest.mark.unit
async def test_valuation_contract_on_an_overvalued_company(session_factory) -> None:
    # Claude down: the agent falls back to its own margin-of-safety rule
    down = await _run_agent(
        "valuation", scenarios.overvalued(), FakeLLM(fail=True), session_factory
    )
    assert down.result is not None
    assert down.result.margin_of_safety < -0.2
    assert down.result.signal == "bearish"
    assert down.result.contract_violations == []

    # Claude bullish on it anyway: kept, but recorded as a broken rule
    bullish = await _run_agent("valuation", scenarios.overvalued(), FakeLLM(), session_factory)
    assert bullish.result is not None and bullish.result.signal == "bullish"
    assert "margin of safety" in bullish.result.contract_violations[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scenario", "expected"), [(scenarios.uptrend, "bullish"), (scenarios.downtrend, "bearish")]
)
async def test_technicals_quant_signal_follows_the_trend(
    scenario, expected: str, session_factory
) -> None:
    quant = await _run_agent("technicals", scenario(), FakeLLM(fail=True), session_factory)
    assert quant.result is not None and quant.result.signal == expected


@pytest.mark.unit
async def test_technicals_contract_flags_a_call_against_a_decisive_composite(
    session_factory,
) -> None:
    llm = FakeLLM(reply={"signal": "bearish", "confidence": 60.0, "reasoning": "contrarian"})
    against = await _run_agent("technicals", scenarios.uptrend(), llm, session_factory)
    assert against.result is not None
    assert against.result.composite >= 0.4
    assert "against a strongly bullish composite" in against.result.contract_violations[0]

    weak = FakeLLM(reply={"signal": "bullish", "confidence": 60.0, "reasoning": "bounce"})
    mild = await _run_agent("technicals", scenarios.downtrend(), weak, session_factory)
    assert mild.result is not None and mild.result.contract_violations == []  # not decisive


@pytest.mark.unit
async def test_fundamentals_contract_on_a_distressed_company(session_factory) -> None:
    quant = await _run_agent(
        "fundamentals", scenarios.distressed(), FakeLLM(fail=True), session_factory
    )
    assert quant.result is not None and quant.result.signal == "bearish"

    bullish = await _run_agent("fundamentals", scenarios.distressed(), FakeLLM(), session_factory)
    assert bullish.result is not None
    assert "majority (bearish)" in bullish.result.contract_violations[0]


@pytest.mark.unit
async def test_risk_override_caps_a_bullish_recommendation_whatever_the_model_says(
    session_factory,
) -> None:
    analysts = {
        name: {"signal": "bullish", "confidence": 80.0, "reasoning": "good"}
        for name in registry.weights()
    }
    analysts["risk"] = {"signal": "bearish", "confidence": 85.0, "reasoning": "covenant breach"}
    llm = FakeLLM(
        reply={
            "signal": "bullish",
            "confidence": 88.0,
            "reasoning": "Strong across the board, risk aside.",
        }
    )
    agent = registry.get("recommendation").agent_cls(
        make_context(llm=llm, results=FakeResults(analysts))
    )
    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)

    result = outcome.result
    assert result is not None
    assert (result.signal, result.action) == ("neutral", "HOLD")
    assert result.confidence <= 55
    assert result.risk_override_applied is True
    assert "Capped at HOLD" in result.reasoning


@pytest.mark.unit
async def test_risk_cap_holds_when_the_model_answers_hold_too_sure(session_factory) -> None:
    # Found by the eval: the model said HOLD itself, at 60%, above the 55% cap
    analysts = {
        name: {"signal": "bullish", "confidence": 75.0, "reasoning": "fine"}
        for name in registry.weights()
    }
    analysts["risk"] = {"signal": "bearish", "confidence": 85.0, "reasoning": "covenant breach"}
    llm = FakeLLM(reply={"signal": "neutral", "confidence": 62.0, "reasoning": "Risk dominates."})
    agent = registry.get("recommendation").agent_cls(
        make_context(llm=llm, results=FakeResults(analysts))
    )
    outcome = await AgentRunner(session_factory, NullKnowledgeStore()).run(agent, "AAPL", RUN_DATE)

    result = outcome.result
    assert result is not None
    assert (result.signal, result.confidence) == ("neutral", 55.0)
    assert result.risk_override_applied is True
    assert "Confidence capped" in result.reasoning


@pytest.mark.unit
def test_risk_invariant_bullish_needs_a_sound_balance_sheet() -> None:
    from app.agents.risk import RiskResult, _bullish_needs_a_sound_balance_sheet

    def risk(signal: str, de: float | None, cr: float | None) -> RiskResult:
        return RiskResult(
            signal=signal,
            confidence=60,
            reasoning="r",
            summary="s",
            debt_to_equity=de,
            current_ratio=cr,
            beta=1.0,
            risk_keywords=[],
        )

    check = _bullish_needs_a_sound_balance_sheet
    assert check(None, risk("bullish", 3.5, 0.8)) == (
        "bullish (low risk) with D/E 3.5 and current ratio 0.80"
    )
    assert check(None, risk("bullish", 3.5, 1.2)) is None
    assert check(None, risk("bearish", 3.5, 0.8)) is None
    assert check(None, risk("bullish", None, 0.8)) is None  # unknown is no evidence


@pytest.mark.unit
def test_earnings_invariant_signal_follows_the_record() -> None:
    from app.agents.earnings import EarningsResult, _signal_follows_the_record

    def earnings(signal: str, rate: float, reaction: float, quarters: int = 4) -> EarningsResult:
        return EarningsResult(
            signal=signal,
            confidence=60,
            reasoning="r",
            summary="s",
            quarters_analyzed=quarters,
            beat_rate=rate,
            avg_surprise_pct=3.0,
            avg_1d_return=reaction,
            next_earnings="Unknown",
        )

    check = _signal_follows_the_record
    assert check(None, earnings("bearish", 1.0, 2.0)) == (
        "bearish with a 100% beat rate and a +2.0% reaction"
    )
    assert check(None, earnings("bullish", 0.25, -1.5)) is not None
    assert check(None, earnings("bearish", 1.0, -2.0)) is None  # beats, but sold off
    assert check(None, earnings("bearish", 1.0, 2.0, quarters=2)) is None  # too few quarters


@pytest.mark.unit
def test_institutional_invariant_signal_follows_the_flow() -> None:
    from app.agents.institutional import InstitutionalResult, _signal_follows_the_flow

    def inst(signal: str, direction: str) -> InstitutionalResult:
        return InstitutionalResult(
            signal=signal,
            confidence=60,
            reasoning="r",
            summary="s",
            institutional_pct=0.6,
            net_share_change=-1.0,
            direction=direction,
            top5_concentration=0.3,
        )

    check = _signal_follows_the_flow
    assert check(None, inst("bullish", "distributing")) == (
        "bullish while institutions are distributing"
    )
    assert check(None, inst("bearish", "accumulating")) is not None
    assert check(None, inst("bullish", "accumulating")) is None
    assert check(None, inst("bullish", "unknown")) is None
