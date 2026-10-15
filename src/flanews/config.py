from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-flash-latest"
    FLAMENGO_TEAM_ID: int = 819  # ESPN team id
    RESEND_API_KEY: str | None = None
    NEWSLETTER_FROM: str = "Urubu News <news@seudominio.com>"
    NEWSLETTER_RECIPIENTS: str | list[str] = ["voce@email.com"]
    TIMEZONE: str = "America/Sao_Paulo"
    DRY_RUN: bool = True
    # Subscription page (flanews.web), served on the VPS.
    PUBLIC_URL: str = "https://flamengo.diegoponte.dev"
    SUBSCRIBE_SECRET: str | None = None  # signs confirmation and unsubscribe links
    SUBSCRIBERS_API_TOKEN: str | None = None  # protects /api/subscribers (and enables it in run)
    SUBSCRIBERS_DB: str = "data/subscribers.db"

    @field_validator("NEWSLETTER_RECIPIENTS")
    @classmethod
    def parse_recipients(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [email.strip() for email in v.split(",") if email.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
