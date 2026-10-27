"""The eval harness, offline: a scripted fake model instead of Claude, so it runs in CI."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.core.clock import utcnow
from app.core.context import current_usage
from app.llm.pricing import TokenUsage
from app.llm.profiles import AgentProfile, ProfileBook
from app.llm.prompt_loader import load_prompt
from app.llm.recording import DbLLMCallRecorder, LLMCallRecord
from evals import capture, cases, compare, report
from evals import run as eval_run
from evals.harness import EvalConfig, Run, estimate, grade, judge_faithfulness, run_case
from tests.factories import RouterStub


class ScriptedLLM(RouterStub):
    """Answers like a sensible model: neutral when told inputs are missing, else bullish."""

    def __init__(self, faithful: bool = True) -> None:
        self.calls: list[dict] = []
        self.faithful = faithful

    def default_model(self, provider: str | None = None) -> str:
        return "claude-haiku-4-5"

    async def generate(self, *, schema: type[BaseModel], prompt: str, **kwargs) -> BaseModel:
        self.calls.append({"prompt": prompt, **kwargs})
        usage = current_usage()
        if usage is not None:
            usage.llm_calls += 1
            usage.input_tokens += 1000
            usage.output_tokens += 80
            usage.cost_usd += 0.0014
        if "faithful" in schema.model_fields:
            claims = [] if self.faithful else ["invented a 40% margin"]
            return schema.model_validate({"faithful": self.faithful, "unsupported_claims": claims})
        signal = "neutral" if "Missing inputs" in prompt else "bullish"
        fields = {
            "signal": signal,
            "confidence": 20.0 if signal == "neutral" else 70.0,
            "reasoning": "ok",
        }
        if "observations" in schema.model_fields:
            fields.update(observations=[], risk_level="low")
        return schema.model_validate(fields)

    async def aclose(self) -> None:
        return None


def _config(llm=None, repeats: int = 2, profiles: dict | None = None) -> EvalConfig:
    return EvalConfig(
        llm=llm or ScriptedLLM(),
        profiles=ProfileBook(profiles or {}),
        reasoning_model="claude-sonnet-4-6",
        repeats=repeats,
    )


@pytest.mark.unit
def test_scenario_suite_covers_every_agent_with_labels() -> None:
    suite = cases.scenario_suite()
    assert {c.agent for c in suite} >= set(cases.ANALYST_AGENTS) | {"recommendation"}
    assert sum(c.labelled for c in suite) >= 20
    assert len({c.case_id for c in suite}) == len(suite)
    assert [c.case_id for c in cases.select(suite, ["valuation"])][:1] == ["no_data/valuation"]


@pytest.mark.unit
async def test_runs_are_graded_for_labels_stability_and_cost() -> None:
    suite = {c.case_id: c for c in cases.scenario_suite()}
    no_data = await run_case(suite["no_data/moat"], _config())
    graded = grade(suite["no_data/moat"], no_data)
    assert graded["label_accuracy"] == 1.0  # told the inputs are missing → neutral
    assert graded["confidence_ok"] == 1.0
    assert graded["stability"] == 1.0
    assert graded["avg_input_tokens"] == 1000
    assert graded["cost_usd"] == pytest.approx(0.0028)

    overvalued = await run_case(suite["overvalued/valuation"], _config())
    graded = grade(suite["overvalued/valuation"], overvalued)
    assert graded["label_accuracy"] == 0.0  # the scripted model is bullish
    assert graded["violation_rate"] == 1.0  # ... which breaks the valuation contract
    assert overvalued[0].prompts and "Margin of safety" in overvalued[0].prompts[0]["prompt"]


@pytest.mark.unit
async def test_recommendation_cases_and_the_risk_override() -> None:
    suite = {c.case_id: c for c in cases.scenario_suite()}
    runs = await run_case(suite["risk_override/recommendation"], _config(repeats=1))
    assert runs[0].signal == "neutral" and runs[0].confidence <= 55  # capped in code
    graded = grade(suite["risk_override/recommendation"], runs)
    assert graded["label_accuracy"] == 1.0 and graded["confidence_ok"] == 1.0


@pytest.mark.unit
async def test_faithfulness_judge() -> None:
    case = next(c for c in cases.scenario_suite() if c.case_id == "no_data/moat")
    for faithful, expected in ((True, 1.0), (False, 0.0)):
        config = _config(llm=ScriptedLLM(faithful=faithful), repeats=1)
        runs = await run_case(case, config)
        await judge_faithfulness(runs, config)
        assert grade(case, runs)["faithfulness"] == expected


@pytest.mark.unit
async def test_estimate_prices_calls_and_flags_unknown_models() -> None:
    suite = cases.select(cases.scenario_suite(), ["valuation", "sentiment"])
    est = await estimate(suite, _config(repeats=3), judge=False)
    assert est.calls > 0 and est.input_tokens > 0
    assert est.cost_usd is not None and est.cost_usd > 0
    unknown = await estimate(suite, _config(profiles={"*": {"model": "mystery"}}), judge=False)
    assert unknown.cost_usd is None and "mystery" in unknown.unpriced_models


@pytest.mark.unit
def test_failed_runs_are_counted_not_raised() -> None:
    case = cases.scenario_suite()[0]
    bad = Run("error", 0, "", [], [], True, 0, 0, 0, None, error="boom")
    graded = grade(case, [bad])
    assert graded["errors"] == 1 and graded["label_accuracy"] is None


@pytest.mark.unit
async def test_cli_estimates_without_running_and_runs_with_yes(tmp_path, capsys) -> None:
    llm = ScriptedLLM()
    code = await eval_run.main(["--agents", "technicals"], llm=llm, out_dir=tmp_path)
    assert code == 0 and llm.calls == []  # estimate only
    assert "Add --yes" in capsys.readouterr().out

    assert await eval_run.main(["--agents", "technicals", "--max-cost", "0"], llm=llm) == 3

    code = await eval_run.main(
        ["--agents", "technicals", "--repeats", "2", "--yes", "--label", "base", "--judge"],
        llm=llm,
        out_dir=tmp_path,
    )
    assert code == 0
    (json_path,) = tmp_path.glob("*-base.json")
    data = json.loads(json_path.read_text())
    assert data["summary"]["cases"] == 4  # no_data, uptrend, downtrend, baseline
    assert data["summary"]["per_agent"]["technicals"]["stability"] == 1.0
    md = json_path.with_suffix(".md").read_text()
    assert "| Label accuracy |" in md and "## Per agent" in md


@pytest.mark.unit
def test_compare_reports() -> None:
    def rep(label: str, acc: float, cost: float) -> dict:
        graded = [
            {
                "case_id": "x",
                "agent": "moat",
                "labelled": True,
                "label_accuracy": acc,
                "confidence_ok": None,
                "stability": 1.0,
                "fallback_rate": 0.0,
                "violation_rate": 0.0,
                "faithfulness": None,
                "errors": 0,
                "avg_input_tokens": 1000.0,
                "avg_output_tokens": 80.0,
                "cost_usd": cost,
            }
        ]
        return {"label": label, "summary": report.summarize(graded), "cases": graded}

    text = report.compare(rep("sonnet", 0.8, 0.01), rep("haiku55", 0.9, 0.001))
    assert "sonnet → haiku55" in text
    assert "+10.0 pp" in text
    assert compare.main(["only-one"]) == 2


@pytest.mark.unit
async def test_capture_exports_ledger_calls_and_replays_them(session_factory, tmp_path) -> None:
    recorder = DbLLMCallRecorder(session_factory)
    for i, (agent, status) in enumerate((("moat", "ok"), ("moat", "ok"), ("risk", "error"))):
        await recorder.record(
            LLMCallRecord(
                call_id=f"c{i}",
                created_at=utcnow() - timedelta(hours=i),
                model="claude-haiku-4-5",
                prompt_name=agent,
                prompt_version="v",
                status=status,
                latency_ms=1,
                usage=TokenUsage(),
                cost_usd=0.0,
                agent=agent,
                system_prompt="sys",
                prompt=f"Symbol: AAPL {i}",
                response='{"signal":"bullish"}',
            )
        )
    rows = await capture.capture(session_factory, days=1, agents=None, per_prompt=1)
    assert [r["call_id"] for r in rows] == ["c0"]  # newest moat call; failures skipped

    rows[0]["expected"] = ["bullish"]
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(rows[0]) + "\n\n")
    (case,) = cases.ledger_suite(path)
    llm = ScriptedLLM()
    runs = await run_case(
        case, _config(llm=llm, repeats=1, profiles={"moat": {"skills": ["moat_evidence"]}})
    )
    assert runs[0].signal == "bullish"
    assert llm.calls[0]["prompt"] == "Symbol: AAPL 0"  # the captured user prompt
    assert "A moat needs evidence" in llm.calls[0]["system"]  # today's prompt + profile skills
    assert grade(case, runs)["label_accuracy"] == 1.0


@pytest.mark.unit
@pytest.mark.parametrize("preset", sorted(p.stem for p in Path("evals/presets").glob("*.json")))
def test_presets_are_valid_profiles(preset: str) -> None:
    overrides = eval_run._load_profiles(f"@evals/presets/{preset}.json")
    book = ProfileBook(overrides)  # unknown fields or skills would raise
    for key in overrides:
        profile = book.resolve(key, AgentProfile())
        if profile.prompt:
            assert load_prompt(profile.prompt)


@pytest.mark.unit
def test_v2_prompts_keep_the_rules_the_contracts_and_compliance_rely_on() -> None:
    recommendation = load_prompt("recommendation_v2")
    for phrase in ("guaranteed", "risk-free", "hype", "main risk", "risk override"):
        assert phrase in recommendation
    for name in ("moat_v2", "risk_v2", "broad_analysis_v2", "growth_v2"):
        text = load_prompt(name)
        assert "max 200 characters" in text and "below 50" in text  # length + missing-data rule


@pytest.mark.unit
async def test_estimate_shows_the_share_of_a_free_tiers_daily_limit() -> None:
    from app.container import build_llm_router
    from app.core.config import Settings
    from app.llm.recording import NullRecorder

    router = build_llm_router(Settings(gemini_api_key="g", groq_api_key="q"), NullRecorder())
    chain = EvalConfig(
        llm=router,
        profiles=ProfileBook(eval_run._load_profiles("@evals/presets/free_chain.json")),
        reasoning_model="r",
    )
    assert eval_run.quota_notes(chain, "anthropic", 250) == [
        "gemini free tier: ~250 of 1000 requests/day (25%)"
    ]
    groq = EvalConfig(llm=router, profiles=ProfileBook(), reasoning_model="r")
    assert eval_run.quota_notes(groq, "groq", 100) == [
        "groq free tier: ~100 of 1000 requests/day (10%)"
    ]
    assert eval_run.quota_notes(groq, "anthropic", 100) == []
    await router.aclose()


@pytest.mark.unit
def test_capture_writes_one_json_object_per_line(tmp_path) -> None:
    out = tmp_path / "nested" / "ledger.jsonl"
    capture.write_jsonl(out, [{"call_id": "c1"}, {"call_id": "c2", "expected": None}])

    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"call_id": "c1"},
        {"call_id": "c2", "expected": None},
    ]


async def _ledger_with_outcomes(session_factory) -> None:
    """Two recommendation calls (AAPL settled at +3% alpha, MSFT still pending) and a moat call."""
    from datetime import date

    from app.models.agent_run import AgentRun
    from app.models.decision_outcome import DecisionOutcome

    recorder = DbLLMCallRecorder(session_factory)
    calls = (("c1", "r1", "recommendation"), ("c2", "r2", "recommendation"), ("c3", "r3", "moat"))
    for call_id, run_id, agent in calls:
        await recorder.record(
            LLMCallRecord(
                call_id=call_id,
                created_at=utcnow(),
                model="claude-haiku-4-5",
                prompt_name=agent,
                prompt_version="v",
                status="ok",
                latency_ms=1,
                usage=TokenUsage(),
                cost_usd=0.0,
                agent=agent,
                run_id=run_id,
                system_prompt="sys",
                prompt=f"prompt {call_id}",
                response='{"signal":"bullish"}',
            )
        )
    day = date(2026, 9, 1)
    async with session_factory() as session:
        for run_id, symbol in (("r1", "AAPL"), ("r2", "MSFT"), ("r3", "AAPL")):
            session.add(
                AgentRun(
                    run_id=run_id,
                    agent_type="x",
                    symbol=symbol,
                    run_date=day,
                    status="completed",
                    started_at=utcnow(),
                    finished_at=utcnow(),
                )
            )
        for symbol, status, horizon in (
            ("AAPL", "settled", 20),
            ("AAPL", "settled", 5),
            ("MSFT", "pending", 20),
        ):
            session.add(
                DecisionOutcome(
                    symbol=symbol,
                    decision_date=day,
                    horizon_days=horizon,
                    benchmark="SPY",
                    status=status,
                    raw_return=0.04 if status == "settled" else None,
                    alpha=0.03 if status == "settled" else None,
                )
            )
        await session.commit()


@pytest.mark.unit
async def test_capture_outcomes_keeps_calls_with_a_settled_outcome(session_factory) -> None:
    await _ledger_with_outcomes(session_factory)

    rows = await capture.capture_outcomes(session_factory, days=1, agents=None)

    assert [r["call_id"] for r in rows] == ["c1"]  # recommendation only; MSFT still pending
    assert rows[0]["outcome"] == {
        "symbol": "AAPL",
        "decision_date": "2026-09-01",
        "horizon": 20,
        "benchmark": "SPY",
        "raw_return": 0.04,
        "alpha": 0.03,
    }
    moat = await capture.capture_outcomes(session_factory, days=1, agents=["moat"], horizon=5)
    assert [r["call_id"] for r in moat] == ["c3"]


@pytest.mark.unit
async def test_outcome_suite_grades_against_realised_alpha(session_factory, tmp_path) -> None:
    await _ledger_with_outcomes(session_factory)
    path = tmp_path / "outcomes.jsonl"
    rows = await capture.capture_outcomes(session_factory, days=1, agents=None)
    plain = {**rows[0], "call_id": "plain"}
    plain.pop("outcome")
    capture.write_jsonl(path, [*rows, plain])

    assert [c.case_id for c in cases.ledger_suite(path)] == ["ledger/c1", "ledger/plain"]
    (case,) = cases.outcome_suite(path)  # only cases that carry an outcome
    assert (case.outcome_alpha, case.outcome_horizon) == (0.03, 20)

    graded = grade(case, await run_case(case, _config(repeats=2)))  # scripted: bullish
    assert (graded["outcome_hit_rate"], graded["alpha_captured"]) == (1.0, 0.03)
    bearish = grade(case, [Run("bearish", 70, "r", [], [], False, 1, 0, 0, None)])
    assert (bearish["outcome_hit_rate"], bearish["alpha_captured"]) == (0.0, -0.03)
    assert grade(cases.scenario_suite()[0], [])["outcome_hit_rate"] is None

    summary = report.summarize([graded, bearish])
    assert summary["outcome_cases"] == 2
    assert summary["outcome_hit_rate"] == 0.5 and summary["alpha_captured"] == 0.0
    assert summary["per_agent"]["recommendation"]["outcome_hit_rate"] == 0.5


@pytest.mark.unit
async def test_cli_runs_the_outcome_suite(tmp_path, session_factory) -> None:
    await _ledger_with_outcomes(session_factory)
    dataset = tmp_path / "outcomes.jsonl"
    capture.write_jsonl(
        dataset, await capture.capture_outcomes(session_factory, days=1, agents=None)
    )

    code = await eval_run.main(
        ["--suite", "outcomes", "--dataset", str(dataset), "--yes", "--label", "o"],
        llm=ScriptedLLM(),
        out_dir=tmp_path,
    )
    assert code == 0
    md = next(tmp_path.glob("*-o.md")).read_text()
    assert "| Outcome hit rate (vs realised alpha) | 100% |" in md
    assert "| Mean alpha captured per call | +3.00% |" in md

    data = json.loads(next(tmp_path.glob("*-o.json")).read_text())
    worse = {**data, "label": "w", "summary": {**data["summary"], "outcome_hit_rate": 0.5}}
    text = report.compare(data, worse)
    assert "| Outcome hit rate | 100% → 50% (-50.0 pp) |" in text
    assert "| Alpha captured per call | +3.00% → +3.00% |" in text
