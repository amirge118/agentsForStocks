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

    # OpenViking — knowledge/memory layer
    openviking_url: str = "http://localhost:1933"
    openviking_api_key: str = ""
    openviking_enabled: bool = True

    # External financial data
    alpha_vantage_key: str = ""


settings = Settings()
