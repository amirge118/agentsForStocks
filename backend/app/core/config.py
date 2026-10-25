"""
Application settings loaded from environment variables.
All values have defaults so the app starts without a .env file (useful in CI).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentsforstocks"

    # Anthropic Claude
    anthropic_api_key: str = ""
    # Cheap + fast model for per-agent judgements; stronger model for the final recommendation
    llm_default_model: str = "claude-haiku-4-5"
    llm_reasoning_model: str = "claude-sonnet-4-6"
    llm_timeout_seconds: float = 30.0

    # OpenViking — knowledge/memory layer
    openviking_url: str = "http://localhost:1933"
    openviking_api_key: str = ""
    openviking_enabled: bool = True

    # External financial data
    alpha_vantage_key: str = ""
    fmp_api_key: str = ""
    fmp_daily_call_limit: int = 250  # FMP free tier
    # SEC requires a descriptive User-Agent with contact info
    edgar_user_agent: str = "agentsForStocks research@agentsforstocks.com"
    # Same-day reruns and agents sharing a data point hit the cache instead of the API
    provider_cache_ttl_seconds: int = 6 * 60 * 60

    # Pipeline
    # Comma-separated symbols, e.g. WATCHLIST=AAPL,MSFT
    watchlist: str = "AAPL,MSFT,NVDA,GOOGL,AMZN,TSLA,META,SPY,QQQ"
    max_concurrent_symbols: int = 2
    max_concurrent_agents: int = 4

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]


settings = Settings()
