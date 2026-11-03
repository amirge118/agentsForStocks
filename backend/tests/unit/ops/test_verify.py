import json
from datetime import date

import pytest

from app.agents.registry import AgentRegistry
from app.agents.runner import RunOutcome
from app.ops.verify import build_report, render
from app.pipeline.orchestrator import PipelineReport
from app.repositories.agent_results import AgentResultRepository
from app.repositories.provider_calls import ProviderCallRepository

DAY = date(2026, 11, 2)


def _registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register("moat", description="m")(type("Moat", (), {}))
    reg.register("sentiment", description="s")(type("Sentiment", (), {}))
    reg.register("recommendation", description="r", depends_on=["moat"])(type("Rec", (), {}))
    return reg


async def _store(session_factory, symbol: str, agent: str, **result) -> None:
    async with session_factory() as session:
        await AgentResultRepository(session).upsert(
            agent_type=agent,
            symbol=symbol,
            run_date=DAY,
            run_id="r",
            result={"signal": "bullish", "confidence": 80.0, "reasoning": "ok", **result},
        )
        await session.commit()


async def _stored_run(session_factory) -> None:
    for symbol in ("AAPL", "XOM"):
        await _store(session_factory, symbol, "moat")
        await _store(session_factory, symbol, "sentiment", data_gaps=["headlines"])
        await _store(
            session_factory,
            symbol,
            "recommendation",
            action="BUY",
            weighted_score=34.0,
            reasoning="Strong moat",
        )
    async with session_factory() as session:
        for _ in range(3):
            await ProviderCallRepository(session).increment("fmp", DAY)
        await session.commit()


def _report(*outcomes: RunOutcome) -> PipelineReport:
    return PipelineReport("p1", DAY, outcomes)


@pytest.mark.unit
async def test_a_clean_run_passes_and_lists_expected_gaps(session_factory) -> None:
    await _stored_run(session_factory)
    run = _report(*(RunOutcome(a, "AAPL", "r", "completed") for a in ("moat", "sentiment")))

    report = await build_report(session_factory, _registry(), run, ["AAPL", "XOM"])

    assert report.verdict == "PASS"  # a missing news feed is listed, not a failure
    assert report.data_gaps == {"moat": {}, "sentiment": {"headlines": 2}, "recommendation": {}}
    assert report.fmp_calls_today == 3
    text = render(report)
    assert "AAPL   BUY  score  +34.0   80%  Strong moat" in text
    assert "sentiment          headlines (2/2)" in text
    assert "moat                ▲  80%   ▲  80% " in text
    assert text.endswith("PASS: every agent ran on every symbol, every judgement came from a model")


@pytest.mark.unit
async def test_a_result_with_no_evidence_is_named_without_failing_the_run(session_factory) -> None:
    await _stored_run(session_factory)
    await _store(
        session_factory,
        "XOM",
        "sentiment",
        signal="neutral",
        confidence=0.0,
        data_gaps=["insider_trades", "headlines"],
    )
    # Honest zero: nothing was missing, so there's nothing to call out
    await _store(session_factory, "AAPL", "moat", signal="neutral", confidence=0.0)

    report = await build_report(session_factory, _registry(), _report(), ["AAPL", "XOM"])

    assert report.verdict == "PASS"
    assert report.no_evidence == ["sentiment/XOM: missing insider_trades, headlines"]
    text = render(report)
    assert "No evidence (neutral at 0%: nothing to judge)" in text
    assert text.endswith("but 1 results had no data to judge, see above")
    assert json.loads(report.to_json())["no_evidence"] == report.no_evidence


@pytest.mark.unit
async def test_results_that_need_review_warn_and_failures_fail(session_factory) -> None:
    await _stored_run(session_factory)
    await _store(session_factory, "XOM", "moat", needs_review=["model unavailable"])

    warn = await build_report(session_factory, _registry(), _report(), ["AAPL", "XOM"])
    assert warn.verdict == "WARN"
    assert warn.needs_review == ["moat/XOM: model unavailable"]
    assert "▲  80%!" in render(warn)

    failed = RunOutcome("moat", "AAPL", "r", "failed", error="FMP down")
    fail = await build_report(session_factory, _registry(), _report(failed), ["AAPL"])
    assert fail.verdict == "FAIL"
    assert "moat/AAPL: FMP down" in render(fail)


@pytest.mark.unit
async def test_skipped_runs_are_read_back_and_noted(session_factory) -> None:
    await _stored_run(session_factory)
    run = _report(RunOutcome("moat", "AAPL", "r", "skipped"))
    report = await build_report(session_factory, _registry(), run, ["AAPL"])
    assert report.symbols[0].agents["moat"].signal == "bullish"
    assert "1 agent runs were already done today" in report.notes[0]


@pytest.mark.unit
async def test_a_symbol_without_results_and_the_json_export(session_factory) -> None:
    report = await build_report(session_factory, _registry(), _report(), ["SPY"])
    assert "SPY    no recommendation" in render(report)
    body = json.loads(report.to_json())
    assert body["verdict"] == "PASS" and body["run_date"] == "2026-11-02"
    assert body["symbols"][0]["symbol"] == "SPY"
