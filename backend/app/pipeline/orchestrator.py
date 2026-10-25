"""
PipelineOrchestrator — runs agents for symbols as a dependency graph.

For each symbol, agents are grouped into levels from the registry (an agent runs
only after everything it depends on); agents within a level run concurrently.
Two semaphores bound the load: how many symbols are processed at once and how
many agents run at once overall — this is what keeps FMP / SEC / Yahoo traffic
within limits instead of fixed cron time slots.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from opentelemetry import trace

from app.agents.base import Agent
from app.agents.registry import AgentRegistry
from app.agents.runner import AgentRunner, RunOutcome
from app.core.clock import market_today
from app.core.context import bind
from app.core.symbols import validate_symbol

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class PipelineReport:
    pipeline_run_id: str
    run_date: date
    outcomes: tuple[RunOutcome, ...] = field(default_factory=tuple)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(o.status for o in self.outcomes))

    @property
    def failed(self) -> list[RunOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def usage(self) -> dict[str, int | float]:
        """LLM totals across the pipeline run (summed from each agent run)."""
        runs = [o.usage for o in self.outcomes if o.usage is not None]
        return {
            "llm_calls": sum(u.llm_calls for u in runs),
            "input_tokens": sum(u.input_tokens for u in runs),
            "output_tokens": sum(u.output_tokens for u in runs),
            "cost_usd": round(sum(u.cost_usd for u in runs), 6),
            "llm_fallbacks": sum(u.llm_fallbacks for u in runs),
        }


class PipelineOrchestrator:
    def __init__(
        self,
        runner: AgentRunner,
        registry: AgentRegistry,
        build_agent: Callable[[str], Agent],
        *,
        max_concurrent_symbols: int = 2,
        max_concurrent_agents: int = 4,
    ) -> None:
        self._runner = runner
        self._registry = registry
        self._build_agent = build_agent
        self._symbol_slots = asyncio.Semaphore(max_concurrent_symbols)
        self._agent_slots = asyncio.Semaphore(max_concurrent_agents)

    async def run(
        self,
        symbols: Iterable[str],
        *,
        agents: Iterable[str] | None = None,
        force: bool = False,
        run_date: date | None = None,
        pipeline_run_id: str | None = None,
    ) -> PipelineReport:
        """
        Run the selected agents (default: all) for each symbol.
        Unknown agents or invalid symbols raise before anything runs.
        Pass pipeline_run_id to correlate with a caller (e.g. an API request).
        """
        tickers = list(dict.fromkeys(validate_symbol(s) for s in symbols))
        levels = self._registry.execution_levels(list(agents) if agents is not None else None)
        day = run_date or market_today()
        pipeline_run_id = pipeline_run_id or str(uuid4())
        with (
            bind(pipeline_run_id=pipeline_run_id),  # inherited by every task gathered below
            tracer.start_as_current_span(
                "pipeline.run",
                attributes={
                    "pipeline.run_id": pipeline_run_id,
                    "pipeline.symbols": tickers,
                    "pipeline.run_date": day.isoformat(),
                    "pipeline.force": force,
                },
            ) as span,
        ):
            logger.info("Pipeline started", extra={"symbols": tickers})
            per_symbol = await asyncio.gather(
                *(
                    self._run_symbol(symbol, levels, day, force, pipeline_run_id)
                    for symbol in tickers
                )
            )
            report = PipelineReport(
                pipeline_run_id=pipeline_run_id,
                run_date=day,
                outcomes=tuple(o for outcomes in per_symbol for o in outcomes),
            )
            for key, value in {**report.counts, **report.usage}.items():
                span.set_attribute(f"pipeline.{key}", value)
            logger.info(
                "Pipeline finished",
                extra={"symbols": tickers, "counts": report.counts, **report.usage},
            )
        return report

    async def _run_symbol(
        self,
        symbol: str,
        levels: list[list[str]],
        run_date: date,
        force: bool,
        pipeline_run_id: str,
    ) -> list[RunOutcome]:
        async with self._symbol_slots:
            with tracer.start_as_current_span("pipeline.symbol", attributes={"symbol": symbol}):
                return await self._run_levels(symbol, levels, run_date, force, pipeline_run_id)

    async def _run_levels(
        self,
        symbol: str,
        levels: list[list[str]],
        run_date: date,
        force: bool,
        pipeline_run_id: str,
    ) -> list[RunOutcome]:
        outcomes: list[RunOutcome] = []
        for level in levels:
            outcomes += await asyncio.gather(
                *(self._run_agent(name, symbol, run_date, force, pipeline_run_id) for name in level)
            )
        return outcomes

    async def _run_agent(
        self, name: str, symbol: str, run_date: date, force: bool, pipeline_run_id: str
    ) -> RunOutcome:
        async with self._agent_slots:
            return await self._runner.run(
                self._build_agent(name),
                symbol,
                run_date,
                force=force,
                pipeline_run_id=pipeline_run_id,
            )
