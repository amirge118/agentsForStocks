"""
Runs eval cases against a model configuration and collects what each run did:
signal, confidence, reasoning, contract violations, fallbacks, tokens and cost —
plus the exact prompts, so a faithfulness judge can check the reasoning.
"""

import logging
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext
from app.agents.catalog import load_agents
from app.agents.contracts import apply_contract, missing_inputs
from app.agents.market_scanner import ScanJudgement
from app.agents.sentiment import NewsSentiment
from app.core.context import bind_run
from app.domain.outcomes import captured_alpha, is_hit
from app.llm.errors import LLMError
from app.llm.pricing import Price
from app.llm.profiles import AgentProfile, ProfileBook
from app.llm.skills import compose_system
from app.schemas.signals import LLMSignal
from evals.cases import EvalCase
from tests.factories import FakeResults

logger = logging.getLogger(__name__)

SYMBOL = "EVAL"
_REPLAY_SCHEMAS: dict[str, type[BaseModel]] = {
    "market_scanner": ScanJudgement,
    "news_sentiment": NewsSentiment,
}
# Rough sizes for the pre-run estimate: ~4 characters per token, plus the JSON
# schema the API adds to every structured request and a typical short reply
CHARS_PER_TOKEN = 4
SCHEMA_OVERHEAD_TOKENS = 150
REPLY_TOKENS = 120


class CapturingLLM:
    """Wraps an LLMRouter and keeps every request and reply of the current run."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.default_provider = inner.default_provider
        self.calls: list[dict[str, Any]] = []

    def default_model(self, provider: str | None = None) -> str | None:
        return self._inner.default_model(provider)

    async def generate(self, **kwargs: Any) -> Any:
        result = await self._inner.generate(**kwargs)
        self.calls.append(
            {
                "prompt_name": kwargs.get("prompt_name"),
                "provider": kwargs.get("provider"),
                "model": kwargs.get("model"),
                "system": kwargs["system"],
                "prompt": kwargs["prompt"],
                "reply": result.model_dump(mode="json"),
            }
        )
        return result

    async def aclose(self) -> None:
        await self._inner.aclose()


class FaithfulnessVerdict(BaseModel):
    faithful: bool
    unsupported_claims: list[str] = Field(description="Claims the input does not support")


@dataclass
class Run:
    signal: str
    confidence: float
    reasoning: str
    violations: list[str]
    data_gaps: list[str]
    fallback: bool
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    prompts: list[dict[str, Any]] = field(default_factory=list)
    faithful: bool | None = None
    unsupported_claims: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class EvalConfig:
    llm: Any  # LLMRouter (or a fake in tests)
    profiles: ProfileBook
    reasoning_model: str
    repeats: int = 1
    judge_model: str | None = None
    judge_provider: str | None = None


async def run_case(case: EvalCase, config: EvalConfig) -> list[Run]:
    return [await _run_once(case, config) for _ in range(config.repeats)]


async def _run_once(case: EvalCase, config: EvalConfig) -> Run:
    llm = CapturingLLM(config.llm)
    try:
        with bind_run(agent=case.agent, symbol=SYMBOL) as usage:
            if case.prompt is not None:
                signal, confidence, reasoning = await _replay(case, llm, config.profiles)
                violations, gaps = [], []
            else:
                result = await _run_agent(case, llm, config)
                signal, confidence, reasoning = result.signal, result.confidence, result.reasoning
                violations, gaps = result.contract_violations, result.data_gaps
    except Exception as exc:  # a broken case is a finding, not a crash of the whole eval
        logger.warning("Eval case failed", extra={"case": case.case_id, "error": str(exc)})
        return Run("error", 0, "", [], [], True, 0, 0, 0, None, error=str(exc))
    return Run(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        violations=list(violations),
        data_gaps=list(gaps),
        fallback=usage.llm_fallbacks > 0,
        llm_calls=usage.llm_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=round(usage.cost_usd, 6) if usage.cost_complete else None,
        prompts=llm.calls,
    )


async def _run_agent(case: EvalCase, llm: CapturingLLM, config: EvalConfig) -> Any:
    registry = load_agents()
    base = case.scenario() if case.scenario else None
    from tests.scenarios import baseline

    data_source = base or baseline()
    ctx = AgentContext(
        yfinance=data_source.yfinance,
        fmp=data_source.fmp,
        edgar=data_source.edgar,
        llm=llm,
        results=case.results() or FakeResults(),
        reasoning_model=config.reasoning_model,
        profiles=config.profiles,
    )
    agent = registry.get(case.agent).agent_cls(ctx)
    data = await agent.fetch(SYMBOL, _run_date())
    agent.data_gaps = missing_inputs(data)
    result = await agent.analyze(SYMBOL, data, [])
    return apply_contract(case.agent, SYMBOL, data, result, agent.invariants)


async def _replay(case: EvalCase, llm: CapturingLLM, book: ProfileBook) -> tuple[str, float, str]:
    """Re-send a captured user prompt with the system prompt of the configuration under test."""
    name = (case.tags[1] if len(case.tags) > 1 and case.tags[1] else case.agent).split("+")[0]
    profile = book.resolve(name, AgentProfile())
    schema = _REPLAY_SCHEMAS.get(name, LLMSignal)
    try:
        reply = await llm.generate(
            system=compose_system(profile.prompt or name, profile.skills),
            prompt=case.prompt or "",
            schema=schema,
            model=profile.model,
            max_tokens=profile.max_tokens or 1024,
            prompt_name=name,
            provider=profile.provider,
        )
    except LLMError:
        from app.core.context import note_fallback

        note_fallback()
        return "neutral", 0.0, ""
    return reply.signal, reply.confidence, reply.reasoning


async def judge_faithfulness(runs: list[Run], config: EvalConfig) -> None:
    """LLM-as-judge: is every factual claim in the reasoning supported by the prompt?"""
    system = load_prompt_file("faithfulness")
    for run in runs:
        if not run.prompts or not run.reasoning:
            continue
        verdict = await config.llm.generate(
            system=system,
            prompt=f"INPUT DATA:\n{run.prompts[-1]['prompt']}\n\nREASONING:\n{run.reasoning}",
            schema=FaithfulnessVerdict,
            model=config.judge_model,
            max_tokens=400,
            prompt_name="eval_faithfulness",
            provider=config.judge_provider,
        )
        run.faithful = verdict.faithful
        run.unsupported_claims = verdict.unsupported_claims


def load_prompt_file(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).parent / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()


def _run_date():  # fixed, so scenario data that depends on dates stays stable
    from datetime import date

    return date(2026, 10, 23)


# ---------------------------------------------------------------- estimate


@dataclass(frozen=True)
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    unpriced_models: tuple[str, ...]


async def estimate(cases: list[EvalCase], config: EvalConfig, judge: bool) -> Estimate:
    """Dry-run every case once against a fake model to size the prompts, then price them."""
    from tests.factories import FakeLLM

    fake = FakeLLM()
    dry = EvalConfig(llm=fake, profiles=config.profiles, reasoning_model=config.reasoning_model)
    calls_per_model: dict[str, list[int]] = {}
    app_logger = logging.getLogger("app")
    level = app_logger.level
    app_logger.setLevel(logging.ERROR)  # the fake's canned answers trip contract warnings
    try:
        for case in cases:
            before = len(fake.calls)
            await _run_once(case, dry)
            _size_calls(fake.calls[before:], config, calls_per_model)
    finally:
        app_logger.setLevel(level)
    return _price_estimate(calls_per_model, config, judge)


def _size_calls(calls: list[dict[str, Any]], config: EvalConfig, out: dict[str, list[int]]) -> None:
    for call in calls:
        model = call["model"] or config.llm.default_model(call["provider"]) or "unknown"
        size = (len(call["system"]) + len(call["prompt"])) // CHARS_PER_TOKEN
        out.setdefault(model, []).append(size + SCHEMA_OVERHEAD_TOKENS)


def _price_estimate(
    calls_per_model: dict[str, list[int]], config: EvalConfig, judge: bool
) -> Estimate:
    repeats = config.repeats
    # (model, prompt sizes, reply tokens per call)
    batches = [(model, sizes, REPLY_TOKENS) for model, sizes in calls_per_model.items()]
    if judge:  # one judge call per agent run: its last prompt plus the reasoning
        judge_model = config.judge_model or config.llm.default_model(config.judge_provider)
        judged = [size + 300 for sizes in calls_per_model.values() for size in sizes]
        batches.append((judge_model or "unknown", judged, 100))
    total_in = total_out = calls = 0
    cost = 0.0
    unpriced: list[str] = []
    for model, sizes, reply in batches:
        n = len(sizes) * repeats
        tokens_in = sum(sizes) * repeats
        tokens_out = n * reply
        calls += n
        total_in += tokens_in
        total_out += tokens_out
        price = _price(model, config)
        if price is None:
            unpriced.append(model)
        else:
            cost += (tokens_in * price.input + tokens_out * price.output) / 1_000_000
    return Estimate(
        calls, total_in, total_out, None if unpriced else round(cost, 4), tuple(unpriced)
    )


def _price(model: str, config: EvalConfig) -> Price | None:
    return config.llm.price(model)


# ---------------------------------------------------------------- grading


def grade(case: EvalCase, runs: list[Run]) -> dict[str, Any]:
    ok = [r for r in runs if r.error is None]
    signals = [r.signal for r in ok]
    confidences = [r.confidence for r in ok]
    mode = max(set(signals), key=signals.count) if signals else None
    judged = [r for r in ok if r.faithful is not None]
    priced = [r.cost_usd for r in ok if r.cost_usd is not None]
    return {
        "case_id": case.case_id,
        "agent": case.agent,
        "labelled": case.labelled,
        "expected": sorted(case.expected) if case.expected else None,
        "runs": len(runs),
        "errors": len(runs) - len(ok),
        "label_accuracy": (
            _share(ok, lambda r: r.signal in case.expected) if case.expected else None
        ),
        "confidence_ok": (
            _share(ok, lambda r: r.confidence <= case.max_confidence)
            if case.max_confidence is not None
            else None
        ),
        "stability": (signals.count(mode) / len(signals)) if signals else None,
        "modal_signal": mode,
        "confidence_mean": round(statistics.fmean(confidences), 1) if confidences else None,
        "confidence_std": round(statistics.pstdev(confidences), 1) if len(confidences) > 1 else 0.0,
        "fallback_rate": _share(runs, lambda r: r.fallback),
        "violation_rate": _share(ok, lambda r: bool(r.violations)),
        "faithfulness": _share(judged, lambda r: bool(r.faithful)) if judged else None,
        **_outcome_grades(case, ok),
        "avg_input_tokens": round(statistics.fmean([r.input_tokens for r in ok]), 0) if ok else 0,
        "avg_output_tokens": round(statistics.fmean([r.output_tokens for r in ok]), 0) if ok else 0,
        "cost_usd": round(sum(priced), 6) if len(priced) == len(ok) else None,
        "samples": [_sample(r) for r in runs[:3]],
    }


def _outcome_grades(case: EvalCase, ok: list[Run]) -> dict[str, Any]:
    """Against what followed: was the call right, and what would following it have earned?"""
    alpha, horizon = case.outcome_alpha, case.outcome_horizon
    if alpha is None or horizon is None:
        return {"outcome_alpha": None, "outcome_hit_rate": None, "alpha_captured": None}
    return {
        "outcome_alpha": alpha,
        "outcome_hit_rate": _share(ok, lambda r: is_hit(r.signal, alpha, horizon)),
        "alpha_captured": (
            round(statistics.fmean(captured_alpha(r.signal, alpha) for r in ok), 5) if ok else None
        ),
    }


def _share(runs: list[Run], predicate: Any) -> float | None:
    return round(sum(1 for r in runs if predicate(r)) / len(runs), 3) if runs else None


def _sample(run: Run) -> dict[str, Any]:
    data = asdict(run)
    data.pop("prompts")
    return data
