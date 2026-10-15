import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from fakes import FakeLLMClient
from pydantic import BaseModel
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews import pipeline
from flanews.config import get_settings
from flanews.models import Article, MatchStats, StandingRow, TeamMoment
from flanews.send.resend_sender import RESEND_URL
from flanews.summarizer.pipeline import (
    AnalysisResponse,
    GroupResponse,
    IntroResponse,
    SummaryResponse,
)

TZ = ZoneInfo("America/Sao_Paulo")
ARTICLE = Article(
    url="https://ge.globo.com/1",
    title="Flamengo vence o Fla-Flu",
    source="ge",
    published_at=datetime(2026, 10, 11, 20, tzinfo=TZ),
    content="O Flamengo venceu.",
)
MATCH = MatchStats(
    fixture_id=1,
    competition="Brasileirão",
    date=datetime(2026, 10, 11, 17, 30, tzinfo=TZ),
    home="Flamengo",
    away="Fluminense",
    home_goals=1,
    away_goals=0,
)


class FakeStats:
    def __init__(self, match: MatchStats | None) -> None:
        self.match = match

    def get_last_match(self, start, end):
        return self.match

    def get_next_match(self, now):
        return None

    def get_standings(self, league="bra.1") -> list[StandingRow]:
        return []

    def get_moment(self, end, standings) -> TeamMoment | None:
        return None


def respond(prompt: str, schema: type[BaseModel]) -> dict:
    return {
        GroupResponse: {"topics": [{"title": "Fla-Flu", "article_ids": [1], "importance": 5}]},
        SummaryResponse: {"summaries": [{"topic_id": 1, "summary": "O Flamengo venceu."}]},
        IntroResponse: {"headline": "Flamengo vence o Fla-Flu", "intro": "Vitória. Líder."},
        AnalysisResponse: {"analysis": "Eficiência decidiu."},
    }[schema]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("NEWSLETTER_FROM", "Flamengo News <news@fla.com>")
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS", "a@x.com")
    get_settings.cache_clear()
    monkeypatch.setattr(pipeline, "get_llm_client", lambda settings: FakeLLMClient(respond))
    yield monkeypatch
    get_settings.cache_clear()


def use(monkeypatch, articles: list[Article], match: MatchStats | None) -> None:
    monkeypatch.setattr(pipeline, "collect_articles", lambda edition, settings: articles)
    monkeypatch.setattr(pipeline, "collect_candidates", lambda edition, settings: ([], []))
    monkeypatch.setattr(pipeline, "ESPNStatsClient", lambda **kwargs: FakeStats(match))


@respx.mock
def test_run_builds_renders_saves_and_sends(env, tmp_path) -> None:
    use(env, [ARTICLE], MATCH)
    route = respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "email_9"}))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert (
        body["subject"]
        == "Flamengo News — Edição de Segunda — 12/10/2026: Flamengo vence o Fla-Flu"
    )
    assert body["bcc"] == ["a@x.com"]
    assert "O Flamengo venceu." in body["html"] and "Eficiência decidiu." in body["text"]
    assert body["headers"]["List-Unsubscribe"] == "<mailto:news@fla.com?subject=Descadastrar>"
    saved = tmp_path / "out" / "newsletter-2026-10-12.html"
    assert saved.read_text(encoding="utf-8") == body["html"]
    assert "email_9" in result.output


@respx.mock
def test_run_refuses_to_send_empty_newsletter(env, tmp_path) -> None:
    use(env, [], None)
    route = respx.post(RESEND_URL)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 1
    assert not route.called
    assert "nada para enviar" in result.output.lower()


@respx.mock
def test_run_sends_stats_only_edition(env) -> None:
    use(env, [], MATCH)
    route = respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "e"}))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    assert route.called


@respx.mock
def test_run_send_failure_exits_with_error(env) -> None:
    use(env, [ARTICLE], MATCH)
    respx.post(RESEND_URL).mock(
        return_value=httpx.Response(403, json={"message": "Domain not verified"})
    )

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 2
    assert "Domain not verified" in result.output


@respx.mock
def test_run_dry_run_saves_but_does_not_send(env, tmp_path) -> None:
    env.setenv("DRY_RUN", "true")
    get_settings.cache_clear()
    use(env, [ARTICLE], MATCH)
    route = respx.post(RESEND_URL)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    assert not route.called
    assert (tmp_path / "out" / "newsletter-2026-10-12.html").exists()
