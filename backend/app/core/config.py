"""
Application settings loaded from environment variables.
All values have defaults so the app starts without a .env file (useful in CI).
"""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_API_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "production" refuses to start without API keys (fail closed)
    environment: Literal["development", "test", "production"] = "development"

    # API authentication: comma-separated keys accepted in the X-API-Key header.
    # Empty = auth disabled, which is only allowed outside production.
    # Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    api_keys: str = ""

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

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key_list)

    @model_validator(mode="after")
    def _check_api_keys(self) -> "Settings":
        if self.environment == "production" and not self.api_key_list:
            raise ValueError("API_KEYS must be set when ENVIRONMENT=production")
        weak = [k for k in self.api_key_list if len(k) < MIN_API_KEY_LENGTH]
        if weak:
            raise ValueError(f"API keys must be at least {MIN_API_KEY_LENGTH} characters")
        return self


settings = Settings()
