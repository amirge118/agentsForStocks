"""
Preflight — checks every external dependency before a real pipeline run and
says exactly what is missing. Used by `python -m scripts.preflight`.

Each check makes at most one small real request through the same clients the
agents use (so retry, rate limits and the FMP budget apply). The LLM check
sends one tiny structured-output request (~100 tokens) to the configured model.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.container import Container
from app.core.config import Settings
from app.schemas.signals import LLMSignal

CheckStatus = Literal["ok", "missing", "failed"]

_PROBE_SYMBOL = "AAPL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    required: bool = True


async def _guard(
    name: str, probe: Callable[[], Awaitable[str]], required: bool = True
) -> CheckResult:
    try:
        return CheckResult(name, "ok", await probe(), required)
    except Exception as exc:  # report every failure; never crash the preflight
        return CheckResult(name, "failed", _explain(exc)[:300], required)


def _explain(exc: BaseException) -> str:
    """The error plus its root cause — retries wrap the real reason (e.g. a proxy 403)."""
    message = f"{type(exc).__name__}: {exc}"
    root = exc
    while root.__cause__ is not None:
        root = root.__cause__
    if root is not exc:
        message += f" ← {type(root).__name__}: {root}"
    return message


async def check_database(session_factory: async_sessionmaker[AsyncSession]) -> CheckResult:
    async def probe() -> str:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            version = (
                await session.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
        return f"connected, migration {version}"

    return await _guard("database", probe)


async def check_yahoo(container: Container) -> CheckResult:
    async def probe() -> str:
        info = await container.agent_context.yfinance.get_info(_PROBE_SYMBOL)
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        if price is None:
            raise RuntimeError("no price in response")
        return f"{_PROBE_SYMBOL} price {price}"

    return await _guard("yahoo_finance", probe)


async def check_edgar(container: Container) -> CheckResult:
    async def probe() -> str:
        text_ = await container.agent_context.edgar.get_business_section(_PROBE_SYMBOL)
        if not text_:
            raise RuntimeError("no 10-K text returned (blocked, or User-Agent rejected)")
        return f"{_PROBE_SYMBOL} 10-K business section, {len(text_):,} chars"

    return await _guard("sec_edgar", probe)


async def check_fmp(container: Container, settings: Settings) -> CheckResult:
    if not settings.fmp_api_key:
        return CheckResult("fmp", "missing", "FMP_API_KEY is not set")

    async def probe() -> str:
        profile = await container.agent_context.fmp.get_company_profile(_PROBE_SYMBOL)
        if not profile:
            raise RuntimeError("empty profile (invalid key or plan limit)")
        name = profile.get("companyName", _PROBE_SYMBOL)
        return f"{name} profile (1 of {settings.fmp_daily_call_limit} daily calls)"

    return await _guard("fmp", probe)


async def check_llm(container: Container, settings: Settings) -> CheckResult:
    if not settings.anthropic_api_key:
        return CheckResult("claude", "missing", "ANTHROPIC_API_KEY is not set")

    async def probe() -> str:
        reply = await container.llm.generate(
            system="You are a health check. Answer with a neutral signal.",
            prompt="Reply with signal=neutral, confidence=0 and reasoning='ok'.",
            schema=LLMSignal,
            max_tokens=100,
        )
        return f"{settings.llm_default_model} structured output ok (signal={reply.signal})"

    return await _guard("claude", probe)


async def check_knowledge(container: Container, settings: Settings) -> CheckResult:
    if not settings.openviking_enabled:
        return CheckResult(
            "openviking", "ok", "disabled (OPENVIKING_ENABLED=false)", required=False
        )

    async def probe() -> str:
        await container.knowledge.recall(_PROBE_SYMBOL, "preflight")
        return "reachable"

    return await _guard("openviking", probe, required=False)


async def run_preflight(
    settings: Settings,
    container: Container,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[CheckResult]:
    return list(
        await asyncio.gather(
            check_database(session_factory),
            check_llm(container, settings),
            check_fmp(container, settings),
            check_yahoo(container),
            check_edgar(container),
            check_knowledge(container, settings),
        )
    )


def ready(results: list[CheckResult]) -> bool:
    return all(r.status == "ok" for r in results if r.required)


def render(results: list[CheckResult]) -> str:
    icon = {"ok": "OK  ", "missing": "MISS", "failed": "FAIL"}
    width = max(len(r.name) for r in results)
    lines = [f"[{icon[r.status]}] {r.name:<{width}}  {r.detail}" for r in results]
    lines.append("")
    lines.append(
        "READY for a real pipeline run" if ready(results) else "NOT READY — fix the items above"
    )
    return "\n".join(lines)
