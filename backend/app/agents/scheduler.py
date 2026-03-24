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
        # Phase 1: original 5 agents (market data + technicals)
        _register_market_scanner(symbol)
        _register_fundamentals(symbol)
        _register_technicals(symbol)
        _register_sentiment(symbol)
        _register_valuation(symbol)
        # Phase 1: new 7 deep-analysis agents (FMP + EDGAR)
        _register_broad_analysis(symbol)
        _register_financial_history(symbol)
        _register_moat(symbol)
        _register_risk(symbol)
        _register_growth(symbol)
        _register_institutional(symbol)
        _register_earnings(symbol)
        # Phase 2: recommendation runs after all Phase 1 agents complete
        _register_recommendation(symbol)

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


def _register_broad_analysis(symbol: str) -> None:
    """Weekdays 20:00 ET — business model + competitive position (FMP + EDGAR)."""
    from app.agents.broad_analysis_agent import BroadAnalysisAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await BroadAnalysisAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=0),
                      id=f"broad_analysis_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_financial_history(symbol: str) -> None:
    """Weekdays 20:05 ET — 5-year financial trend analysis (FMP)."""
    from app.agents.financial_history_agent import FinancialHistoryAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await FinancialHistoryAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=5),
                      id=f"financial_history_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_moat(symbol: str) -> None:
    """Weekdays 20:10 ET — competitive moat assessment (EDGAR + FMP)."""
    from app.agents.moat_agent import MoatAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await MoatAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=10),
                      id=f"moat_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_risk(symbol: str) -> None:
    """Weekdays 20:15 ET — risk factor analysis (EDGAR + FMP + yfinance)."""
    from app.agents.risk_agent import RiskAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await RiskAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=15),
                      id=f"risk_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_growth(symbol: str) -> None:
    """Weekdays 20:20 ET — growth potential from transcripts + analyst estimates (FMP)."""
    from app.agents.growth_agent import GrowthAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await GrowthAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=20),
                      id=f"growth_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_institutional(symbol: str) -> None:
    """Weekdays 20:25 ET — institutional 13F ownership trend (FMP)."""
    from app.agents.institutional_agent import InstitutionalAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await InstitutionalAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=25),
                      id=f"institutional_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_earnings(symbol: str) -> None:
    """Weekdays 20:30 ET — earnings surprise history + post-earnings reaction (FMP + yfinance)."""
    from app.agents.earnings_agent import EarningsAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await EarningsAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=30),
                      id=f"earnings_{symbol}", replace_existing=True, misfire_grace_time=3600)


def _register_recommendation(symbol: str) -> None:
    """Weekdays 21:00 ET — final weighted recommendation (Phase 2, after all Phase 1 agents)."""
    from app.agents.recommendation_agent import RecommendationAgent
    from app.db.session import AsyncSessionLocal
    from app.services.knowledge_service import get_knowledge_service

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await RecommendationAgent(db=db, knowledge=get_knowledge_service()).run(symbol=symbol)

    scheduler.add_job(_run, trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=0),
                      id=f"recommendation_{symbol}", replace_existing=True, misfire_grace_time=3600)
