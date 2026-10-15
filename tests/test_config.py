import pytest

from flanews.config import Settings, get_settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.GEMINI_MODEL == "gemini-flash-latest"
    assert settings.FLAMENGO_TEAM_ID == 819
    assert settings.TIMEZONE == "America/Sao_Paulo"
    assert settings.DRY_RUN is True
    assert settings.NEWSLETTER_RECIPIENTS == ["voce@email.com"]


def test_settings_custom_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("FLAMENGO_TEAM_ID", "123")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key")
    monkeypatch.setenv("NEWSLETTER_FROM", "Sender <news@fla.com>")
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS", "a@test.com, b@test.com , c@test.com")
    monkeypatch.setenv("TIMEZONE", "UTC")
    monkeypatch.setenv("DRY_RUN", "false")

    # Clear cache before retrieving
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.GEMINI_API_KEY == "test-gemini-key"
    assert settings.GEMINI_MODEL == "gemini-2.5-flash"
    assert settings.FLAMENGO_TEAM_ID == 123
    assert settings.RESEND_API_KEY == "test-resend-key"
    assert settings.NEWSLETTER_FROM == "Sender <news@fla.com>"
    assert settings.NEWSLETTER_RECIPIENTS == ["a@test.com", "b@test.com", "c@test.com"]
    assert settings.TIMEZONE == "UTC"
    assert settings.DRY_RUN is False

    get_settings.cache_clear()


def test_public_url_defaults_to_the_urubu_news_domain() -> None:
    assert Settings().PUBLIC_URL == "https://urubunews.diegoponte.dev"
