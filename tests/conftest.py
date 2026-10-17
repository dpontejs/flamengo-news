import pytest

from flanews.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep the developer's .env and exported settings out of the tests.

    Settings reads `.env` from the working directory, so every test runs from an
    empty temporary directory with no project variables in the environment.
    """
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_espn_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI plans editions from ESPN's calendar; tests start from an empty one, offline."""
    import flanews.__main__ as cli

    monkeypatch.setattr(cli, "_fixtures", lambda settings, now: [])
