"""Each agent: fetch wiring, analysis with a judging LLM, fallback when the LLM is down."""

from datetime import date

import pandas as pd
import pytest

from app.agents.broad_analysis import BroadAnalysisAgent
from app.agents.earnings import EarningsAgent
from app.agents.financial_history import FinancialHistoryAgent
from app.agents.fundamentals import FundamentalsAgent
from app.agents.growth import GrowthAgent
from app.agents.institutional import InstitutionalAgent
from app.agents.market_scanner import MarketScannerAgent
from app.agents.moat import MoatAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.risk import RiskAgent
from app.agents.sentiment import SentimentAgent
from app.agents.technicals import TechnicalsAgent
from app.agents.valuation import ValuationAgent
from tests.factories import FakeEdgar, FakeFmp, FakeLLM, FakeResults, FakeYFinance, make_context

RUN_DATE = date(2026, 10, 23)
ANALYSTS = [
    MarketScannerAgent,
    FundamentalsAgent,
    TechnicalsAgent,
    SentimentAgent,
    ValuationAgent,
    BroadAnalysisAgent,
    FinancialHistoryAgent,
    MoatAgent,
    RiskAgent,
    GrowthAgent,
    InstitutionalAgent,
    EarningsAgent,
]


async def _run(agent_cls, **ctx_kwargs):
    ctx = make_context(**ctx_kwargs)
    agent = agent_cls(ctx)
    data = await agent.fetch("AAPL", RUN_DATE)
    return agent, await agent.analyze("AAPL", data, ["remembered pattern"])


@pytest.mark.unit
@pytest.mark.parametrize("agent_cls", ANALYSTS, ids=lambda c: c.__name__)
async def test_agent_uses_llm_judgement_and_prompt_context(agent_cls) -> None:
    llm = FakeLLM()
    agent, result = await _run(agent_cls, llm=llm)

    assert isinstance(result, agent_cls.result_model)
    assert result.signal == "bullish"
    assert result.confidence == 70.0
    assert result.summary
    final_call = llm.calls[-1]
    assert "AAPL" in final_call["prompt"]
    assert "remembered pattern" in final_call["prompt"]
    result.model_dump(mode="json")  # must be JSON-serialisable for the DB


@pytest.mark.unit
@pytest.mark.parametrize("agent_cls", ANALYSTS, ids=lambda c: c.__name__)
async def test_agent_completes_when_llm_is_down(agent_cls) -> None:
    _, result = await _run(agent_cls, llm=FakeLLM(fail=True))
    assert "unavailable" in result.reasoning.lower()
    assert 0 <= result.confidence <= 100


@pytest.mark.unit
@pytest.mark.parametrize("agent_cls", ANALYSTS, ids=lambda c: c.__name__)
async def test_agent_handles_empty_provider_data(agent_cls) -> None:
    empty_fmp = FakeFmp(
        profile={},
        income=[],
        balance=[],
        cash_flow=[],
        ratios=[],
        key_metrics=[],
        surprises=[],
        transcripts={},
        estimates=[],
        holders=[],
        ownership=[],
    )

    class EmptyYF(FakeYFinance):
        async def get_insider_transactions(self, symbol: str) -> list[dict]:
            return []

        async def get_news(self, symbol: str, count: int = 20) -> list[dict]:
            return []

        async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

    _, result = await _run(
        agent_cls,
        yfinance=EmptyYF(info={}, history=pd.DataFrame()),
        fmp=empty_fmp,
        edgar=FakeEdgar(business=" ", risk=" "),
    )
    assert result.signal in ("bullish", "bearish", "neutral")


@pytest.mark.unit
async def test_quant_fallback_keeps_computed_signal() -> None:
    """Technicals on a strong uptrend stays bullish even without Claude."""
    _, result = await _run(TechnicalsAgent, llm=FakeLLM(fail=True))
    assert result.signal == "bullish"
    assert result.composite > 0


@pytest.mark.unit
async def test_technicals_short_history_skips_llm() -> None:
    llm = FakeLLM()
    _, result = await _run(TechnicalsAgent, llm=llm, yfinance=FakeYFinance(history=pd.DataFrame()))
    assert result.confidence == 0.0
    assert llm.calls == []


@pytest.mark.unit
async def test_sentiment_classifies_news_with_llm() -> None:
    llm = FakeLLM()
    _, result = await _run(SentimentAgent, llm=llm)
    assert [c["schema"].__name__ for c in llm.calls] == ["_NewsSentiment", "LLMSignal"]
    assert result.insider.signal == "bullish"
    assert result.news.detail == "2 headlines analyzed"


@pytest.mark.unit
async def test_growth_falls_back_to_previous_year_transcripts() -> None:
    fmp = FakeFmp(transcripts={(2025, 4): {"quarter": 4, "year": 2025, "content": "Q4 call"}})
    _, result = await _run(GrowthAgent, fmp=fmp)
    assert (2025, 4) in fmp.transcript_requests
    assert result.transcript_available


@pytest.mark.unit
async def test_market_scanner_records_volume_spike_pattern() -> None:
    agent, result = await _run(MarketScannerAgent)
    assert result.metrics["volume_ratio"] == 3.0
    kinds = [learning.kind for learning in agent.learnings("AAPL", result)]
    assert kinds == ["case", "pattern"]


@pytest.mark.unit
async def test_learnings_patterns() -> None:
    agent, result = await _run(MoatAgent)
    assert [lr.kind for lr in agent.learnings("AAPL", result)] == ["case", "pattern"]
    agent, result = await _run(RiskAgent)
    assert "litigation" in agent.learnings("AAPL", result)[1].content
    agent, result = await _run(InstitutionalAgent)
    assert "accumulating" in agent.learnings("AAPL", result)[1].content
    agent, result = await _run(EarningsAgent)
    assert "beater" in agent.learnings("AAPL", result)[1].content
    agent, result = await _run(
        FinancialHistoryAgent,
        fmp=FakeFmp(
            income=[
                {"date": "2025", "revenue": 200.0},
                {"date": "2024", "revenue": 100.0},
            ]
        ),
    )
    assert "growing" in agent.learnings("AAPL", result)[1].content


@pytest.mark.unit
async def test_earnings_without_data_records_no_misser_pattern() -> None:
    """Regression: 0 quarters used to be stored as a 'frequent earnings misser'."""
    agent, result = await _run(EarningsAgent, fmp=FakeFmp(surprises=[]))
    assert result.quarters_analyzed == 0
    assert [lr.kind for lr in agent.learnings("AAPL", result)] == ["case"]


@pytest.mark.unit
async def test_earnings_frequent_misser_pattern() -> None:
    misses = [{"date": "2025-10-30", "actualEarningResult": 1.0, "estimatedEarning": 1.5}] * 4
    agent, result = await _run(EarningsAgent, fmp=FakeFmp(surprises=misses))
    assert "misser" in agent.learnings("AAPL", result)[1].content


def _analyst_results(signal: str, confidence: float = 90.0) -> dict[str, dict]:
    names = [
        "financial_history",
        "valuation",
        "moat",
        "risk",
        "broad_analysis",
        "growth",
        "institutional",
        "earnings",
    ]
    return {n: {"signal": signal, "confidence": confidence, "reasoning": n} for n in names}


@pytest.mark.unit
async def test_recommendation_uses_reasoning_model_and_weights() -> None:
    llm = FakeLLM()
    _, result = await _run(
        RecommendationAgent, llm=llm, results=FakeResults(_analyst_results("bullish"))
    )
    assert result.action == "BUY"
    assert result.weighted_score == pytest.approx(90.0)
    assert result.agents_missing == []
    assert llm.calls[0]["model"] == "reasoning-model"


@pytest.mark.unit
async def test_recommendation_breakdown_carries_each_analysts_compliance_review() -> None:
    results = _analyst_results("bullish")
    results["moat"]["compliance"] = {
        "status": "fail",
        "findings": [{"rule": "promissory_language", "severity": "fail", "phrase": "risk-free"}],
    }
    _, result = await _run(RecommendationAgent, llm=FakeLLM(), results=FakeResults(results))

    by_agent = {c.agent: c for c in result.agent_breakdown}
    assert by_agent["moat"].compliance_status == "fail"
    assert [f.model_dump() for f in by_agent["moat"].compliance_findings] == [
        {"rule": "promissory_language", "severity": "fail", "phrase": "risk-free"}
    ]
    assert by_agent["valuation"].compliance_status is None
    assert by_agent["valuation"].compliance_findings == []


@pytest.mark.unit
async def test_recommendation_holds_without_enough_analysts() -> None:
    llm = FakeLLM()
    partial = dict(list(_analyst_results("bullish").items())[:2])
    _, result = await _run(RecommendationAgent, llm=llm, results=FakeResults(partial))
    assert result.action == "HOLD"
    assert len(result.agents_missing) == 6
    assert llm.calls == []


@pytest.mark.unit
async def test_recommendation_fallback_uses_rule_based_score() -> None:
    _, result = await _run(
        RecommendationAgent,
        llm=FakeLLM(fail=True),
        results=FakeResults(_analyst_results("bearish")),
    )
    assert result.action == "SELL"


@pytest.mark.unit
async def test_judge_passes_mcp_servers_to_the_llm() -> None:
    from app.llm.mcp import McpServer

    llm = FakeLLM()
    agent = MoatAgent(make_context(llm=llm))
    server = McpServer(name="daloopa", url="https://mcp.daloopa.com/mcp")
    await agent.judge("prompt", fallback=None, mcp_servers=[server])
    assert llm.calls[0]["mcp_servers"] == [server]


def _recommend_with(reasoning: str, signal: str = "bullish"):
    llm = FakeLLM({"signal": signal, "confidence": 75.0, "reasoning": reasoning})
    return _run(RecommendationAgent, llm=llm, results=FakeResults(_analyst_results("bullish")))


@pytest.mark.unit
async def test_compliant_recommendation_reasoning_is_kept() -> None:
    from app.domain.compliance import DISCLAIMER

    text = "Strong history and valuation; main risk is slowing growth."
    _, result = await _recommend_with(text)
    assert result.reasoning == text
    assert result.compliance.status == "pass"
    assert result.compliance.findings == []
    assert result.disclaimer == DISCLAIMER


@pytest.mark.unit
async def test_promissory_recommendation_reasoning_is_replaced() -> None:
    from app.domain.compliance import review_recommendation

    text = "Guaranteed gains — a risk-free buy."
    _, result = await _recommend_with(text)
    assert result.compliance.status == "fail"
    assert result.compliance.original_reasoning == text
    assert "Guaranteed" not in result.reasoning
    assert "Guaranteed" not in result.summary
    assert result.reasoning.startswith("Weighted analyst score +90.0")
    assert "financial_history bullish" in result.reasoning
    # The replacement text must itself pass review
    assert review_recommendation(result.reasoning, "bullish").status == "pass"


@pytest.mark.unit
async def test_flagged_recommendation_reasoning_is_kept_with_findings() -> None:
    _, result = await _recommend_with("Great growth and strong margins.")
    assert result.compliance.status == "flag"
    assert result.compliance.findings[0].rule == "missing_risk_discussion"
    assert result.reasoning == "Great growth and strong margins."
