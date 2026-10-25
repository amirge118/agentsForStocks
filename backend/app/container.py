"""
Composition root — the one place that constructs concrete dependencies.

Everything else receives what it needs through constructors, which keeps
modules decoupled and lets tests swap in fakes (see tests/factories.py).
"""

from dataclasses import dataclass

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import Agent, AgentContext
from app.agents.catalog import load_agents
from app.agents.registry import AgentRegistry
from app.agents.runner import AgentRunner, SessionResultsReader
from app.core.config import Settings
from app.knowledge.openviking_store import OpenVikingStore
from app.knowledge.store import KnowledgeStore, NullKnowledgeStore
from app.llm.client import LLMClient
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.pricing import Price
from app.llm.profiles import ProfileBook
from app.llm.recording import DbLLMCallRecorder, LLMCallRecorder
from app.llm.router import ALT, ANTHROPIC, LLMProvider, LLMRouter
from app.pipeline.launcher import PipelineLauncher
from app.pipeline.orchestrator import PipelineOrchestrator
from app.providers.cache import TTLCache
from app.providers.edgar import EdgarClient
from app.providers.fmp import DailyCallBudget, FmpClient
from app.providers.http import HttpClient
from app.providers.rate_limit import RateLimiter
from app.providers.yfinance import YFinanceClient

# Requests per second per domain (SEC allows 10/s; stay well below every limit)
_RATE_LIMITS = {
    "financialmodelingprep.com": 4.0,
    "www.sec.gov": 5.0,
    "data.sec.gov": 5.0,
    "yahoo": 2.0,
}


@dataclass
class Container:
    settings: Settings
    registry: AgentRegistry
    agent_context: AgentContext
    knowledge: KnowledgeStore
    runner: AgentRunner
    orchestrator: PipelineOrchestrator
    launcher: PipelineLauncher
    session_factory: async_sessionmaker[AsyncSession]
    http: HttpClient
    llm: LLMRouter

    def build_agent(self, name: str) -> Agent:
        return self.registry.get(name).agent_cls(self.agent_context)

    async def aclose(self) -> None:
        await self.launcher.aclose()
        await self.http.aclose()
        await self.llm.aclose()


def build_llm_router(settings: Settings, recorder: LLMCallRecorder) -> LLMRouter:
    """Claude always; the OpenAI-compatible provider when LLM_ALT_* is configured."""
    providers: dict[str, LLMProvider] = {
        ANTHROPIC: LLMClient(
            anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key or None,
                timeout=settings.llm_timeout_seconds,
                max_retries=2,  # SDK retries 429/5xx/connection errors with backoff
            ),
            default_model=settings.llm_default_model,
            recorder=recorder,
            capture_content=settings.llm_capture_content,
        )
    }
    if settings.alt_llm_configured:
        price = Price(
            input=settings.llm_alt_input_price,
            output=settings.llm_alt_output_price,
            cache_read=settings.llm_alt_input_price,
            cache_write=settings.llm_alt_input_price,
        )
        providers[ALT] = OpenAICompatibleClient(
            base_url=settings.llm_alt_base_url,
            api_key=settings.llm_alt_api_key,
            default_model=settings.llm_alt_model,
            recorder=recorder,
            capture_content=settings.llm_capture_content,
            prices={settings.llm_alt_model: price},
            timeout_seconds=settings.llm_alt_timeout_seconds,
        )
    return LLMRouter(providers, default_provider=settings.llm_provider)


def build_container(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Container:
    rate_limiter = RateLimiter(_RATE_LIMITS)
    cache = TTLCache(ttl_seconds=settings.provider_cache_ttl_seconds)
    http = HttpClient(rate_limiter=rate_limiter, cache=cache)
    llm = build_llm_router(settings, DbLLMCallRecorder(session_factory))
    knowledge: KnowledgeStore = (
        OpenVikingStore(settings.openviking_url, settings.openviking_api_key or None)
        if settings.openviking_enabled
        else NullKnowledgeStore()
    )
    context = AgentContext(
        yfinance=YFinanceClient(rate_limiter=rate_limiter, cache=cache),
        fmp=FmpClient(http, settings.fmp_api_key, DailyCallBudget(settings.fmp_daily_call_limit)),
        edgar=EdgarClient(http, settings.edgar_user_agent),
        llm=llm,
        results=SessionResultsReader(session_factory),
        reasoning_model=settings.llm_reasoning_model,
        profiles=ProfileBook.from_config(settings.agent_profiles, settings.agent_profiles_file),
    )
    registry = load_agents()
    runner = AgentRunner(session_factory, knowledge)
    orchestrator = PipelineOrchestrator(
        runner,
        registry,
        build_agent=lambda name: registry.get(name).agent_cls(context),
        max_concurrent_symbols=settings.max_concurrent_symbols,
        max_concurrent_agents=settings.max_concurrent_agents,
    )
    return Container(
        settings=settings,
        registry=registry,
        agent_context=context,
        knowledge=knowledge,
        runner=runner,
        orchestrator=orchestrator,
        launcher=PipelineLauncher(orchestrator, registry),
        session_factory=session_factory,
        http=http,
        llm=llm,
    )
