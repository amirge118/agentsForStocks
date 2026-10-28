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
    assert [c["schema"].__name__ for c in llm.calls] == ["NewsSentiment", "LLMSignal"]
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
    misses = [{"date": "2025-10-30", "epsActual": 1.0, "epsEstimated": 1.5}] * 4
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
    # A HOLD for lack of analysts is not a view on the stock
    assert result.needs_review == ["only 2/8 analysts reported"]


@pytest.mark.unit
async def test_recommendation_names_analysts_that_fell_back() -> None:
    results = _analyst_results("bullish")
    results["moat"]["needs_review"] = ["model unavailable for 1 judgement"]
    _, result = await _run(RecommendationAgent, llm=FakeLLM(), results=FakeResults(results))
    assert result.needs_review == ["analysts needing review: moat"]
    by_agent = {c.agent: c.needs_review for c in result.agent_breakdown}
    assert by_agent["moat"] and not by_agent["valuation"]
    clean = await _run(
        RecommendationAgent, llm=FakeLLM(), results=FakeResults(_analyst_results("bullish"))
    )
    assert clean[1].needs_review == []


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


@pytest.mark.unit
def test_results_from_a_judgement_share_one_summary_format() -> None:
    from app.agents.moat import MoatResult
    from app.schemas.signals import LLMSignal

    judgement = LLMSignal(signal="bullish", confidence=72.4, reasoning="Durable brand")
    fields = dict(avg_gross_margin=0.4, gross_margin_variance=0.01, intangibles_pct=0.1)
    plain = MoatResult.from_judgement("Moat", judgement, moat_keywords=[], **fields)
    assert plain.summary == "Moat: bullish (72%) — Durable brand"
    assert (plain.signal, plain.confidence, plain.reasoning) == ("bullish", 72.4, "Durable brand")
    detailed = MoatResult.from_judgement(
        "Moat", judgement, detail="keywords=2", moat_keywords=["brand", "network"], **fields
    )
    assert detailed.summary == "Moat: bullish (72%) keywords=2 — Durable brand"


@pytest.mark.unit
async def test_unreported_figures_reach_the_model_as_na_never_as_zero() -> None:
    """A missing D/E is not "debt-free", a missing current ratio not distress."""
    llm = FakeLLM()
    _, risk = await _run(RiskAgent, llm=llm, yfinance=FakeYFinance(info={}), fmp=FakeFmp(ratios=[]))
    assert (risk.debt_to_equity, risk.current_ratio, risk.beta) == (None, None, None)
    prompt = llm.calls[0]["prompt"]
    assert "Debt/equity:   N/A" in prompt and "Current ratio: N/A" in prompt
    assert "0.00" not in prompt

    llm = FakeLLM()
    _, inst = await _run(
        InstitutionalAgent, llm=llm, yfinance=FakeYFinance(info={}), fmp=FakeFmp(holders=[])
    )
    assert (inst.institutional_pct, inst.net_share_change, inst.direction) == (
        None,
        None,
        "unknown",
    )
    assert "Net change across top holders: N/A shares (unknown)" in llm.calls[0]["prompt"]

    llm = FakeLLM()
    _, broad = await _run(
        BroadAnalysisAgent, llm=llm, yfinance=FakeYFinance(info={}), fmp=FakeFmp(profile={})
    )
    assert broad.market_cap_b is None
    assert "Market cap: N/A" in llm.calls[0]["prompt"]


@pytest.mark.unit
def test_debt_to_equity_units_and_a_true_zero() -> None:
    from app.agents.risk import debt_to_equity_ratio

    assert debt_to_equity_ratio({"debtToEquityRatio": 0.0}, {"debtToEquity": 150}) == 0.0
    assert debt_to_equity_ratio({}, {"debtToEquity": 150}) == 1.5  # yfinance: percent
    assert debt_to_equity_ratio({}, {}) is None


@pytest.mark.unit
async def test_sentiment_takes_insider_trades_from_sec_when_yahoo_has_none() -> None:
    from app.agents.sentiment import SentimentAgent
    from app.core.clock import market_today

    class NoInsiderYF(FakeYFinance):
        async def get_insider_transactions(self, symbol: str) -> list[dict]:
            return []

    today = market_today().isoformat()
    form4 = [{"Start Date": today, "Transaction": "Purchase", "source": "SEC Form 4"}] * 2
    _, result = await _run(SentimentAgent, yfinance=NoInsiderYF(), edgar=FakeEdgar(insider=form4))
    assert result.insider.detail.startswith("buys=2 sells=0")
    assert "insider_trades" not in result.data_gaps


@pytest.mark.unit
async def test_earnings_takes_the_next_report_from_fmp_when_yahoo_has_none() -> None:
    from app.domain.earnings import scheduled_report

    rows = [
        {"date": "2026-11-02", "epsActual": None},
        {"date": "2026-07-30", "epsActual": 1.5},
        {"date": "2026-01-29", "epsActual": None},  # a past row never filled in
    ]
    assert scheduled_report(rows, RUN_DATE) == "2026-11-02"
    assert scheduled_report(rows[1:], RUN_DATE) == "Unknown"

    class NoCalendarYF(FakeYFinance):
        async def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

    from datetime import timedelta

    from app.core.clock import market_today

    soon = (market_today() + timedelta(days=5)).isoformat()
    _, result = await _run(
        EarningsAgent,
        yfinance=NoCalendarYF(),
        fmp=FakeFmp(surprises=[{"date": soon, "epsActual": None, "epsEstimated": 1.0}]),
    )
    assert result.next_earnings == soon


@pytest.mark.unit
async def test_growth_reads_the_sec_earnings_release_without_a_transcript() -> None:
    from app.agents.growth import GrowthAgent

    release = {
        "date": "2026-07-30",
        "content": "Record June quarter.",
        "source": "8-K Exhibit 99.1",
    }
    llm = FakeLLM()
    _, result = await _run(
        GrowthAgent, llm=llm, fmp=FakeFmp(transcripts={}), edgar=FakeEdgar(release=release)
    )
    assert result.earnings_release_used and not result.transcript_available
    assert "transcripts" not in result.data_gaps
    prompt = llm.calls[0]["prompt"]
    assert "--- Earnings release, 8-K Exhibit 99.1 (2026-07-30) ---\nRecord June quarter." in prompt

    _, with_transcript = await _run(GrowthAgent, edgar=FakeEdgar(release=release))
    assert with_transcript.transcript_available and not with_transcript.earnings_release_used
