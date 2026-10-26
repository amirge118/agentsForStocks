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

    # Logging: "text" for development, "json" (one object per line) for production
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentsforstocks"

    # Anthropic Claude
    anthropic_api_key: str = ""
    # Cheap + fast model for per-agent judgements; stronger model for the final recommendation
    llm_default_model: str = "claude-haiku-4-5"
    llm_reasoning_model: str = "claude-sonnet-4-6"
    llm_timeout_seconds: float = 30.0
    # Default provider for every agent prompt: "anthropic" (Claude), "chain" (free
    # providers first, see LLM_CHAIN), one free provider ("gemini", "groq", "cerebras")
    # or "alt" (below). Per-agent choices go in AGENT_PROFILES — see app/llm/profiles.py
    llm_provider: str = "anthropic"
    # Fallback order for provider "chain": each step is provider[:model]; steps whose
    # provider has no API key are skipped (app/llm/chain.py)
    llm_chain: str = "gemini,groq,cerebras,anthropic:claude-haiku-5-5"

    # Free tiers (app/llm/providers_catalog.py) — each joins once its key is set
    gemini_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    # Overrides for those providers (model, quotas, ...) or extra ones (JSON, inline/file)
    llm_providers: str = ""
    llm_providers_file: str = ""
    # A free provider that would need a longer wait for its rate limit is skipped
    llm_quota_max_wait_seconds: float = 5.0

    # A second, cheaper provider: any OpenAI-compatible chat-completions API with
    # JSON-schema outputs (Gemini, OpenRouter, DeepSeek, a local Ollama, …)
    llm_alt_base_url: str = ""
    llm_alt_api_key: str = ""
    llm_alt_model: str = ""
    # USD per million tokens, for the ledger's cost column (0 = free tier / local)
    llm_alt_input_price: float = 0.0
    llm_alt_output_price: float = 0.0
    llm_alt_timeout_seconds: float = 60.0

    # Agent profile overrides (JSON, inline and/or a file) — provider, model, skills,
    # max_tokens, use_llm per prompt. Example: {"news_sentiment": {"provider": "alt"}}
    agent_profiles: str = ""
    agent_profiles_file: str = ""
    # Ledger (llm_calls): keep the exact prompt and reply text of every call, for review
    # and evals; rows older than the retention window are deleted daily by the worker
    llm_capture_content: bool = True
    llm_call_retention_days: int = 90

    # OpenTelemetry (traces, metrics, logs over OTLP/HTTP). The exporters read the
    # standard OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS variables.
    otel_enabled: bool = False

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

    # Scheduled jobs (app/agents/scheduler.py) — OFF by default: nothing runs on its own
    # until SCHEDULER_ENABLED=true. Each job's timing is a crontab line in New York time;
    # an empty value turns that one job off. `python -m scripts.schedules` lists them.
    scheduler_enabled: bool = False
    pipeline_schedule: str = "30 18 * * mon-fri"  # full pipeline, after the US close
    maintenance_schedule: str = "15 3 * * *"  # prune the llm_calls ledger
    # Where the scheduler lives: inside the API process (development), or — in production,
    # RUN_SCHEDULER=false on the API — in exactly one `python -m app.worker`.
    run_scheduler: bool = True
    # Initial watchlist, comma-separated (WATCHLIST=AAPL,MSFT). Only seeds the `watchlist`
    # table once (migration 0005); after that the list is managed through /api/v1/watchlist.
    watchlist: str = "AAPL,MSFT,NVDA,GOOGL,AMZN"
    max_concurrent_symbols: int = 2
    max_concurrent_agents: int = 4

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def alt_llm_configured(self) -> bool:
        return bool(self.llm_alt_base_url and self.llm_alt_model)

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
