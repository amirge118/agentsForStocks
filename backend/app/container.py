"""
Composition root — the one place that constructs concrete dependencies.

Everything else receives what it needs through constructors, which keeps
modules decoupled and lets tests swap in fakes (see tests/factories.py).
"""

import logging
import os
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
from app.llm.chain import FallbackChain, parse_chain
from app.llm.client import LLMClient
from app.llm.openai_compat import OpenAICompatibleClient
from app.llm.profiles import ProfileBook
from app.llm.provider import ALT, ANTHROPIC, LLMProvider
from app.llm.providers_catalog import alt_spec, configured, load_specs
from app.llm.quota import ProviderQuota, UsageLoader
from app.llm.recording import DbLLMCallRecorder, LedgerUsage, LLMCallRecorder
from app.llm.router import LLMRouter
from app.pipeline.launcher import PipelineLauncher
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.settlement import OutcomeSettler
from app.providers.cache import TTLCache
from app.providers.edgar import EdgarClient
from app.providers.fmp import DailyCallBudget, FmpClient
from app.providers.http import HttpClient
from app.providers.rate_limit import RateLimiter
from app.providers.yfinance import YFinanceClient

logger = logging.getLogger(__name__)

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
    settler: OutcomeSettler

    def build_agent(self, name: str) -> Agent:
        return self.registry.get(name).agent_cls(self.agent_context)

    async def aclose(self) -> None:
        await self.launcher.aclose()
        await self.http.aclose()
        await self.llm.aclose()


def build_llm_router(
    settings: Settings, recorder: LLMCallRecorder, usage: UsageLoader | None = None
) -> LLMRouter:
    """
    Claude always; each free provider whose API key is set (app/llm/providers_catalog.py);
    the OpenAI-compatible "alt" provider when LLM_ALT_* is configured; and "chain",
    which tries them in LLM_CHAIN order. `usage` seeds the free-tier quotas from the ledger.
    """
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
    specs = load_specs(settings.llm_providers, settings.llm_providers_file)
    if settings.alt_llm_configured:
        specs[ALT] = alt_spec(
            settings.llm_alt_base_url,
            settings.llm_alt_model,
            input_price=settings.llm_alt_input_price,
            output_price=settings.llm_alt_output_price,
            timeout_seconds=settings.llm_alt_timeout_seconds,
        )
    for spec, key in configured(specs, _provider_keys(settings)):
        providers[spec.name] = OpenAICompatibleClient(
            base_url=spec.base_url,
            api_key=key,
            default_model=spec.model,
            name=spec.name,
            structured_mode=spec.structured_mode,
            extra_body=spec.extra_body,
            reasoning_tokens=spec.reasoning_tokens,
            quota=(
                ProviderQuota(
                    spec.name,
                    spec.limits,
                    max_wait_seconds=settings.llm_quota_max_wait_seconds,
                    load_usage=usage,
                )
                if spec.limits.bounded
                else None
            ),
            recorder=recorder,
            capture_content=settings.llm_capture_content,
            prices={spec.model: spec.price},
            timeout_seconds=spec.timeout_seconds,
        )
    # Claude without a key would only add a failed call to every chain run
    in_chain = {
        name: client
        for name, client in providers.items()
        if name != ANTHROPIC or settings.anthropic_api_key
    }
    chain = FallbackChain(parse_chain(settings.llm_chain), in_chain)
    router = LLMRouter(providers, default_provider=settings.llm_provider, chain=chain)
    if not router.configured(settings.llm_provider):
        logger.warning(
            "LLM_PROVIDER is not configured — agents will use their rule-based fallback",
            extra={"provider": settings.llm_provider},
        )
    return router


def _provider_keys(settings: Settings) -> dict[str, str]:
    """API keys by variable name: the built-in ones from settings (.env), others from env."""
    return {
        **os.environ,
        "LLM_ALT_API_KEY": settings.llm_alt_api_key,
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GROQ_API_KEY": settings.groq_api_key,
        "CEREBRAS_API_KEY": settings.cerebras_api_key,
    }


def build_container(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Container:
    rate_limiter = RateLimiter(_RATE_LIMITS)
    cache = TTLCache(ttl_seconds=settings.provider_cache_ttl_seconds)
    http = HttpClient(rate_limiter=rate_limiter, cache=cache)
    llm = build_llm_router(
        settings, DbLLMCallRecorder(session_factory), usage=LedgerUsage(session_factory)
    )
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
        settler=OutcomeSettler(
            session_factory, context.yfinance, benchmark=settings.outcome_benchmark
        ),
    )
