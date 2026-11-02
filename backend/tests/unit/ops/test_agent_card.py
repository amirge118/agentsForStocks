from datetime import UTC, date, datetime, timedelta

import pytest

from app.agents.catalog import load_agents
from app.llm.profiles import ProfileBook
from app.models.agent_run import AgentRun
from app.models.decision_outcome import DecisionOutcome
from app.ops.agent_card import EvalCoverage, build_card, hints, render_card
from app.repositories.agent_results import AgentResultRepository
from tests.unit.test_llm_call_repository import _record

TODAY = date(2026, 10, 30)
SINCE = TODAY - timedelta(days=14)


def _run(run_id: str, day: date, status: str = "completed", **fields) -> AgentRun:
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return AgentRun(
        run_id=run_id,
        agent_type=fields.pop("agent", "valuation"),
        symbol=fields.pop("symbol", "AAPL"),
        run_date=day,
        status=status,
        started_at=at,
        finished_at=at,
        **fields,
    )


async def _card(session_factory, agent: str = "valuation", **kw):
    async with session_factory() as session:
        return await build_card(
            session,
            load_agents(),
            agent,
            since=SINCE,
            today=TODAY,
            profiles=kw.pop("profiles", ProfileBook()),
            **kw,
        )


@pytest.mark.unit
async def test_card_reads_runs_results_calls_and_outcomes(session_factory) -> None:
    from app.llm.recording import DbLLMCallRecorder

    async with session_factory() as session:
        session.add_all(
            [
                _run("r1", TODAY, analyze_ms=200, llm_fallbacks=1),
                _run("r2", TODAY - timedelta(days=1), analyze_ms=400),
                _run("r3", TODAY - timedelta(days=2), "failed", error="FMP 429"),
                _run("old", TODAY - timedelta(days=40)),  # outside the window
                _run("other", TODAY, agent="moat"),  # another agent
            ]
        )
        results = AgentResultRepository(session)
        for symbol, day, gaps, violations in [
            ("AAPL", TODAY, ["fmp.cash_flow"], []),
            ("AAPL", TODAY - timedelta(days=1), [], ["bullish with MoS +5%"]),
            ("MSFT", TODAY, ["fmp.cash_flow", "yfinance.info"], []),
        ]:
            await results.upsert(
                agent_type="valuation",
                symbol=symbol,
                run_date=day,
                run_id="r",
                result={
                    "signal": "bearish",
                    "confidence": 70,
                    "data_gaps": gaps,
                    "contract_violations": violations,
                },
            )
        session.add(
            DecisionOutcome(
                symbol="AAPL",
                decision_date=TODAY,
                horizon_days=20,
                benchmark="SPY",
                status="settled",
                exit_date=TODAY + timedelta(days=28),
                raw_return=-0.03,
                alpha=-0.04,
            )
        )
        await session.commit()
    recorder = DbLLMCallRecorder(session_factory)
    await recorder.record(_record("c1", agent="valuation", provider="gemini", cost=0.0))
    await recorder.record(_record("c2", agent="valuation", provider="groq", status="error"))
    await recorder.record(_record("c3", agent="moat"))

    card = await _card(
        session_factory,
        profiles=ProfileBook({"valuation": {"prompt": "valuation_v2"}}),
        evals=EvalCoverage(cases=5, labelled=4),
    )

    assert (card.runs.total, card.runs.completed, card.runs.failed) == (3, 2, 1)
    assert card.runs.llm_fallbacks == 1 and card.runs.avg_analyze_ms == 300
    assert card.runs.last_error == "FMP 429"
    assert [(c.symbol, c.run_date) for c in card.latest] == [("AAPL", TODAY), ("MSFT", TODAY)]
    assert (card.results, card.results_with_gaps) == (3, 2)
    assert card.data_gaps == {"fmp.cash_flow": 2, "yfinance.info": 1}
    assert card.violations == {"bullish with MoS +5%": 1}
    assert {u.key for u in card.llm_by_provider} == {"gemini", "groq"}  # moat's call left out
    assert card.profile.prompt == "valuation_v2"
    assert "valuation.md" in card.prompt_files
    assert card.snapshot == "tests/snapshots/prompts/valuation.txt"
    assert card.track is not None and card.track.overall.calls == 1
    assert card.track.overall.hits == 1  # bearish before a -4% alpha

    text = render_card(card)
    assert text.startswith("Agent: valuation — ")
    assert "3 runs: 2 completed, 1 failed, 0 skipped · 1 LLM fallbacks" in text
    assert "Data gaps: 2/3 results (67%)" in text
    assert "1 settled calls · hit rate 100%" in text
    assert "Eval coverage: 5 scenario case(s), 4 labelled" in text
    assert "prompt valuation_v2" in text


@pytest.mark.unit
async def test_hints_point_at_the_first_thing_to_fix(session_factory) -> None:
    empty = await _card(session_factory, "moat", evals=EvalCoverage(1, 0))
    assert len(empty.hints) == 1 and "No runs in this window" in empty.hints[0]
    assert "run_pipeline AAPL --agents moat" in render_card(empty)

    async with session_factory() as session:
        session.add_all(
            [_run(f"r{i}", TODAY, agent="moat", llm_fallbacks=1) for i in range(3)]
            + [_run("f", TODAY, "failed", agent="moat", error="boom")]
        )
        await AgentResultRepository(session).upsert(
            agent_type="moat",
            symbol="AAPL",
            run_date=TODAY,
            run_id="r",
            result={
                "signal": "neutral",
                "confidence": 20,
                "data_gaps": ["edgar.business"],
                "contract_violations": ["x"],
            },
        )
        await session.commit()
    card = await _card(session_factory, "moat", evals=EvalCoverage(1, 0))
    text = " | ".join(card.hints)
    assert card.hints[0].startswith("1 failed run(s)") and "boom" in card.hints[0]
    for expected in (
        "Data before prompt",
        "Contract violations",
        "fallback(s) in 4 runs",
        "Only 0 labelled eval case(s)",
        "No settled outcomes yet",
    ):
        assert expected in text


@pytest.mark.unit
def test_quiet_card_has_no_hints(session_factory) -> None:
    from dataclasses import replace

    from app.domain.outcomes import AgentTrack, TrackStats
    from app.llm.profiles import AgentProfile
    from app.ops.agent_card import AgentCard, RunStats

    card = AgentCard(
        agent="risk",
        description="d",
        since=SINCE,
        profile=AgentProfile(),
        prompt_files=(),
        snapshot=None,
        runs=RunStats(total=5, completed=5),
        latest=(),
        results=5,
        results_with_gaps=1,
        data_gaps={},
        violations={},
        llm_by_provider=(),
        llm_by_prompt=(),
        track=AgentTrack("risk", TrackStats(3, 2, 0.01), {}, {}),
        pending_outcomes=0,
        evals=None,
    )
    assert hints(card) == ()
    assert "nothing stands out" in render_card(replace(card, hints=hints(card)))


@pytest.mark.unit
async def test_unknown_agent_is_a_clear_error(session_factory) -> None:
    with pytest.raises(KeyError, match="Unknown agent 'nope'; known: .*valuation"):
        await _card(session_factory, "nope")


@pytest.mark.unit
async def test_script_prints_the_card(session_factory, monkeypatch, capsys) -> None:
    from scripts import agent_card

    monkeypatch.setattr(agent_card, "AsyncSessionLocal", session_factory)
    assert await agent_card.main(["recommendation"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Agent: recommendation")
    assert "Eval coverage:" in out and "labelled" in out
    assert await agent_card.main(["nope"]) == 2
    assert "Unknown agent 'nope'" in capsys.readouterr().err
