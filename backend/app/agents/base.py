"""
Agent — the contract for every stock analysis agent.

An agent only describes *what* to analyse:
  fetch(symbol)                   — gather raw data through the providers (I/O only)
  analyze(symbol, data, memory)   — compute with app.domain, ask Claude to judge,
                                    return a typed AnalysisResult
  learnings(symbol, result)       — what to remember in the knowledge base

*How* a run happens (idempotency, logging, persistence, knowledge writes,
error handling) lives in AgentRunner, so agents stay small and testable.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import note_fallback
from app.domain.signals import SignalLabel
from app.knowledge.store import Learning
from app.llm.client import LLMError
from app.llm.mcp import McpServer
from app.llm.profiles import AgentProfile, ProfileBook
from app.llm.router import ANTHROPIC, LLMRouter
from app.llm.skills import compose_system, prompt_label
from app.providers.edgar import EdgarClient
from app.providers.fmp import FmpClient
from app.providers.yfinance import YFinanceClient
from app.schemas.signals import LLMSignal

logger = logging.getLogger(__name__)


class ComplianceFindingView(BaseModel):
    rule: str
    severity: Literal["flag", "fail"]
    phrase: str


class ComplianceView(BaseModel):
    status: Literal["pass", "flag", "fail"]
    findings: list[ComplianceFindingView]
    original_reasoning: str | None = None


class AnalysisResult(BaseModel):
    """Fields every agent result has. Agents subclass it to add their own metrics."""

    model_config = ConfigDict(extra="forbid")

    signal: SignalLabel
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str
    summary: str
    # Set by AgentRunner before the result is stored:
    # inputs that came back empty, and broken contract rules (app/agents/contracts.py)
    data_gaps: list[str] = Field(default_factory=list)
    contract_violations: list[str] = Field(default_factory=list)
    # ... and the compliance review of the reasoning (app/agents/compliance.py)
    compliance: ComplianceView | None = None


class ResultsReader(Protocol):
    """Read access to stored results — used by agents that build on other agents."""

    async def get_for_date(
        self, symbol: str, run_date: date, agent_types: list[str]
    ) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True)
class AgentContext:
    """Everything an agent may depend on. Built once in app.container."""

    yfinance: YFinanceClient
    fmp: FmpClient
    edgar: EdgarClient
    llm: LLMRouter
    results: ResultsReader
    reasoning_model: str
    # Per-prompt model/provider/skill configuration (app/llm/profiles.py)
    profiles: ProfileBook = field(default_factory=ProfileBook)


DataT = TypeVar("DataT")
ResultT = TypeVar("ResultT", bound=AnalysisResult)
T = TypeVar("T", bound=BaseModel)


class Agent(ABC, Generic[DataT, ResultT]):
    # Set by @register_agent
    name: ClassVar[str]
    result_model: ClassVar[type[AnalysisResult]]
    invariants: ClassVar[tuple[Any, ...]] = ()
    default_profile: ClassVar[AgentProfile] = AgentProfile()

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        # Inputs that came back empty — set by AgentRunner before analyze(); judge()
        # tells Claude about them so it doesn't judge missing data as if it were there
        self.data_gaps: list[str] = []

    @abstractmethod
    async def fetch(self, symbol: str, run_date: date) -> DataT:
        """Gather raw data. No analysis here."""

    @abstractmethod
    async def analyze(self, symbol: str, data: DataT, memory: list[str]) -> ResultT:
        """Turn data (+ recalled knowledge) into a result."""

    def learnings(self, symbol: str, result: ResultT) -> list[Learning]:
        """Default: remember the run summary as a case. Override to add patterns."""
        return [Learning(kind="case", content=result.summary)]

    def with_data_gaps(self, prompt: str) -> str:
        """Append a note naming the inputs that came back empty (no-op when none did)."""
        if not self.data_gaps:
            return prompt
        return (
            f"{prompt}\n\nMissing inputs (the data sources returned nothing): "
            f"{', '.join(self.data_gaps)}. Judge only what is present above and lower your "
            "confidence accordingly; with no usable data, answer neutral."
        )

    @property
    def profile(self) -> AgentProfile:
        """The effective profile of the agent's main prompt (defaults + configuration)."""
        return self.ctx.profiles.resolve(self.name, type(self).default_profile)

    async def ask(
        self,
        prompt: str,
        *,
        schema: type[T],
        fallback: T,
        prompt_name: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        mcp_servers: list[McpServer] | None = None,
    ) -> T:
        """
        The one way agents call a model. The prompt's profile decides provider,
        model, skills and budget; missing inputs are named in the prompt. When the
        model is unavailable — or switched off by the profile — return `fallback`,
        so the run still completes.
        """
        name = prompt_name or self.name
        profile = self.ctx.profiles.resolve(name, type(self).default_profile)
        if not profile.use_llm:
            return fallback
        provider = profile.provider or self.ctx.llm.default_provider
        # A model hint (e.g. the reasoning model) names a Claude model, so it only
        # applies when the call goes to Claude
        chosen = profile.model or (model if provider == ANTHROPIC else None)
        try:
            return await self.ctx.llm.generate(
                system=compose_system(profile.prompt or name, profile.skills),
                prompt=self.with_data_gaps(prompt),
                schema=schema,
                model=chosen,
                max_tokens=profile.max_tokens or max_tokens,
                mcp_servers=mcp_servers,
                prompt_name=prompt_label(profile.prompt or name, profile.skills),
                provider=provider,
            )
        except LLMError as exc:
            note_fallback()
            logger.warning(
                "LLM judgement unavailable, using fallback",
                extra={"agent": self.name, "prompt_name": name, "error": str(exc)},
            )
            return fallback

    async def judge(
        self,
        prompt: str,
        *,
        fallback: LLMSignal,
        prompt_name: str | None = None,
        model: str | None = None,
        mcp_servers: list[McpServer] | None = None,
    ) -> LLMSignal:
        """
        Ask the model for the final signal with the agent's system prompt
        (app/llm/prompts/<name>.md). The fallback is usually the agent's own
        quantitative signal.
        """
        profile = self.ctx.profiles.resolve(prompt_name or self.name, type(self).default_profile)
        if not profile.use_llm:
            return fallback.model_copy(
                update={"reasoning": fallback.reasoning.replace(_UNAVAILABLE, _RULE_BASED, 1)}
            )
        return await self.ask(
            prompt,
            schema=LLMSignal,
            fallback=fallback,
            prompt_name=prompt_name,
            model=model,
            mcp_servers=mcp_servers,
        )


_UNAVAILABLE = "LLM unavailable"
_RULE_BASED = "Rule-based (LLM off for this agent)"


def neutral_fallback(reason: str = "LLM unavailable — no quantitative signal") -> LLMSignal:
    return LLMSignal(signal="neutral", confidence=0.0, reasoning=reason)


def quant_fallback(signal: SignalLabel, confidence: float, what: str) -> LLMSignal:
    """Fallback that keeps the agent's computed signal when Claude is unavailable."""
    return LLMSignal(
        signal=signal,
        confidence=min(max(confidence, 0.0), 100.0),
        reasoning=f"LLM unavailable — {what}",
    )
