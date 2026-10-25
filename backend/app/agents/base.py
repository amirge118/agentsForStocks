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
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.context import note_fallback
from app.domain.signals import SignalLabel
from app.knowledge.store import Learning
from app.llm.client import LLMClient, LLMError
from app.llm.mcp import McpServer
from app.llm.prompt_loader import load_prompt
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
    # Set by AgentRunner (app/agents/compliance.py) before the result is stored
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
    llm: LLMClient
    results: ResultsReader
    reasoning_model: str


DataT = TypeVar("DataT")
ResultT = TypeVar("ResultT", bound=AnalysisResult)


class Agent(ABC, Generic[DataT, ResultT]):
    # Set by @register_agent
    name: ClassVar[str]
    result_model: ClassVar[type[AnalysisResult]]

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    @abstractmethod
    async def fetch(self, symbol: str, run_date: date) -> DataT:
        """Gather raw data. No analysis here."""

    @abstractmethod
    async def analyze(self, symbol: str, data: DataT, memory: list[str]) -> ResultT:
        """Turn data (+ recalled knowledge) into a result."""

    def learnings(self, symbol: str, result: ResultT) -> list[Learning]:
        """Default: remember the run summary as a case. Override to add patterns."""
        return [Learning(kind="case", content=result.summary)]

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
        Ask Claude for the final signal using the agent's system prompt
        (app/llm/prompts/<name>.md). If Claude is unavailable, return `fallback` —
        usually the agent's own quantitative signal — so the run still completes.
        """
        try:
            name = prompt_name or self.name
            return await self.ctx.llm.generate(
                system=load_prompt(name),
                prompt=prompt,
                schema=LLMSignal,
                model=model,
                mcp_servers=mcp_servers,
                prompt_name=name,
            )
        except LLMError as exc:
            note_fallback()
            logger.warning(
                "LLM judgement unavailable, using fallback",
                extra={
                    "agent": self.name,
                    "error": str(exc),
                },
            )
            return fallback


def neutral_fallback(reason: str = "LLM unavailable — no quantitative signal") -> LLMSignal:
    return LLMSignal(signal="neutral", confidence=0.0, reasoning=reason)


def quant_fallback(signal: SignalLabel, confidence: float, what: str) -> LLMSignal:
    """Fallback that keeps the agent's computed signal when Claude is unavailable."""
    return LLMSignal(
        signal=signal,
        confidence=min(max(confidence, 0.0), 100.0),
        reasoning=f"LLM unavailable — {what}",
    )
