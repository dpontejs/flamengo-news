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
    API_FOOTBALL_KEY: str | None = None
    FLAMENGO_TEAM_ID: int = 127
    RESEND_API_KEY: str | None = None
    NEWSLETTER_FROM: str = "Flamengo News <news@seudominio.com>"
    NEWSLETTER_RECIPIENTS: str | list[str] = ["voce@email.com"]
    TIMEZONE: str = "America/Sao_Paulo"
    DRY_RUN: bool = True

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
