"""
Agent scheduler — registers and triggers all agents on a cron schedule.
Uses APScheduler with AsyncIOScheduler so jobs run inside the FastAPI event loop.

Symbols to track are loaded from DB or env at startup.
All jobs are idempotent — safe to re-trigger manually.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="America/New_York")

# Default watchlist — override via DB or env in production
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "SPY", "QQQ"]


def register_all_agents(symbols: list[str] | None = None) -> None:
    """
    Register all agent jobs. Call once at app startup (lifespan).
    Jobs run on New York time to align with market close.
    """
    watch = symbols or DEFAULT_SYMBOLS

    for symbol in watch:
        _register_market_scanner(symbol)
        _register_fundamentals(symbol)
        _register_technicals(symbol)
        _register_sentiment(symbol)
        _register_valuation(symbol)

    logger.info("Registered agent jobs for %d symbols: %s", len(watch), watch)


def _register_market_scanner(symbol: str) -> None:
    """Weekdays 18:30 ET — broad price/volume/technical scan."""
    from app.agents.market_scanner import MarketScannerAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await MarketScannerAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30),
                      id=f"market_scanner_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_fundamentals(symbol: str) -> None:
    """Weekdays 19:00 ET — 4-factor fundamental analysis."""
    from app.agents.fundamentals_agent import FundamentalsAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await FundamentalsAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=0),
                      id=f"fundamentals_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_technicals(symbol: str) -> None:
    """Weekdays 19:15 ET — 5-strategy technical analysis."""
    from app.agents.technicals_agent import TechnicalsAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await TechnicalsAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=15),
                      id=f"technicals_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_sentiment(symbol: str) -> None:
    """Weekdays 19:30 ET — insider + news sentiment analysis."""
    from app.agents.sentiment_agent import SentimentAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await SentimentAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=30),
                      id=f"sentiment_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_valuation(symbol: str) -> None:
    """Weekdays 19:45 ET — DCF + Owner Earnings + EV/EBITDA valuation."""
    from app.agents.valuation_agent import ValuationAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await ValuationAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=45),
                      id=f"valuation_{symbol}", replace_existing=True, misfire_grace_time=3600)
