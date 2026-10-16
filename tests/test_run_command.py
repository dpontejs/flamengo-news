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
from flanews.send.resend_sender import RESEND_BATCH_URL as RESEND_URL
from flanews.send.resend_sender import UNSUBSCRIBE_PLACEHOLDER
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


def sent(ids: list[str]) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": i} for i in ids]})


def use(monkeypatch, articles: list[Article], match: MatchStats | None) -> None:
    monkeypatch.setattr(pipeline, "collect_articles", lambda edition, settings: articles)
    monkeypatch.setattr(pipeline, "collect_candidates", lambda edition, settings: ([], []))
    monkeypatch.setattr(pipeline, "ESPNStatsClient", lambda **kwargs: FakeStats(match))


@respx.mock
def test_run_builds_renders_saves_and_sends(env, tmp_path) -> None:
    use(env, [ARTICLE], MATCH)
    route = respx.post(RESEND_URL).mock(return_value=sent(["email_9"]))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    [body] = json.loads(route.calls.last.request.content)
    assert (
        body["subject"] == "Urubu News — Edição de Segunda — 12/10/2026: Flamengo vence o Fla-Flu"
    )
    assert body["to"] == ["a@x.com"]
    assert "O Flamengo venceu." in body["html"] and "Eficiência decidiu." in body["text"]
    assert body["headers"]["List-Unsubscribe"] == "<mailto:news@fla.com?subject=Descadastrar>"
    saved = tmp_path / "out" / "newsletter-2026-10-12.html"
    assert saved.read_text(encoding="utf-8") == body["html"]
    assert "enviada para 1 destinatário" in result.output
    assert "Inscreva-se" not in body["html"]  # page link only once subscriptions are live


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
    route = respx.post(RESEND_URL).mock(return_value=sent(["e"]))

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


@respx.mock
def test_run_writes_report_to_github_step_summary(env, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    env.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def collect(edition, settings):
        import logging

        logging.getLogger("flanews.collectors.ge").warning("ge fora do ar")
        return [ARTICLE]

    env.setattr(pipeline, "collect_articles", collect)
    env.setattr(pipeline, "collect_candidates", lambda edition, settings: ([], []))
    env.setattr(pipeline, "ESPNStatsClient", lambda **kwargs: FakeStats(MATCH))
    respx.post(RESEND_URL).mock(return_value=sent(["email_9"]))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    report = summary.read_text(encoding="utf-8")
    assert "## Urubu News — Edição de Segunda — 12/10/2026" in report
    assert "**Resultado:** enviada para 1 destinatário" in report
    assert "Destinatários: 1 (0 pela página de inscrição)" in report
    assert "| ge | 1 |" in report
    assert "- Fla-Flu" in report
    assert "Última partida: ✅" in report
    assert "ge fora do ar" in report


@respx.mock
def test_run_reports_empty_edition(env, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    env.setenv("GITHUB_STEP_SUMMARY", str(summary))
    use(env, [], None)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 1
    assert "**Resultado:** nada para enviar" in summary.read_text(encoding="utf-8")


@respx.mock
def test_run_reports_send_failure_and_prints_without_github(env) -> None:
    use(env, [ARTICLE], MATCH)
    respx.post(RESEND_URL).mock(
        return_value=httpx.Response(403, json={"message": "Domain not verified"})
    )

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 2
    assert "**Resultado:** falha no envio" in result.output


API = "https://news.test/api/subscribers"


@respx.mock
def test_run_sends_to_api_subscribers_with_one_click_unsubscribe(env, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    env.setenv("GITHUB_STEP_SUMMARY", str(summary))
    env.setenv("SUBSCRIBERS_API_TOKEN", "api-token")
    env.setenv("PUBLIC_URL", "https://news.test")
    get_settings.cache_clear()
    use(env, [ARTICLE], MATCH)
    respx.get(API).mock(
        return_value=httpx.Response(
            200, json=[{"email": "ana@y.com", "unsubscribe_url": "https://news.test/u?token=A"}]
        )
    )
    route = respx.post(RESEND_URL).mock(return_value=sent(["e1", "e2"]))
    respx.put("https://news.test/api/latest-edition").mock(return_value=httpx.Response(204))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    owner, ana = json.loads(route.calls.last.request.content)
    assert owner["to"] == ["a@x.com"] and ana["to"] == ["ana@y.com"]
    assert 'href="https://news.test/u?token=A"' in ana["html"]
    assert ana["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert 'href="https://news.test"' in ana["html"] and "Inscreva-se" in ana["html"]
    report = summary.read_text(encoding="utf-8")
    assert "enviada para 2 destinatários" in report
    assert "Destinatários: 2 (1 pela página de inscrição)" in report


@respx.mock
def test_run_survives_subscribers_api_failure(env, tmp_path, monkeypatch) -> None:
    summary = tmp_path / "summary.md"
    env.setenv("GITHUB_STEP_SUMMARY", str(summary))
    env.setenv("SUBSCRIBERS_API_TOKEN", "api-token")
    env.setenv("PUBLIC_URL", "https://news.test")
    get_settings.cache_clear()
    use(env, [ARTICLE], MATCH)
    monkeypatch.setattr("flanews.send.recipients.FETCH_ATTEMPTS", 1)
    respx.get(API).mock(side_effect=httpx.ConnectError("vps down"))
    respx.put("https://news.test/api/latest-edition").mock(side_effect=httpx.ConnectError("down"))
    route = respx.post(RESEND_URL).mock(return_value=sent(["e1"]))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    [owner] = json.loads(route.calls.last.request.content)
    assert owner["to"] == ["a@x.com"]
    report = summary.read_text(encoding="utf-8")
    assert "Destinatários: 1 (0 pela página de inscrição)" in report
    assert "vps down" in report


PUBLISH = "https://news.test/api/latest-edition"


def enable_subscriptions(env) -> None:
    env.setenv("SUBSCRIBERS_API_TOKEN", "api-token")
    env.setenv("PUBLIC_URL", "https://news.test")
    get_settings.cache_clear()
    respx.get(API).mock(return_value=httpx.Response(200, json=[]))


@respx.mock
def test_run_publishes_the_edition_for_new_subscribers_after_a_real_send(env) -> None:
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    respx.post(RESEND_URL).mock(return_value=sent(["e1"]))
    publish = respx.put(PUBLISH).mock(return_value=httpx.Response(204))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    request = publish.calls.last.request
    assert request.headers["Authorization"] == "Bearer api-token"
    body = json.loads(request.content)
    assert body["subject"].startswith("Urubu News — Edição de Segunda")
    assert UNSUBSCRIBE_PLACEHOLDER in body["html"] and UNSUBSCRIBE_PLACEHOLDER in body["text"]
    assert "mailto:" not in body["html"]


@respx.mock
def test_dry_run_does_not_publish_the_edition(env) -> None:
    env.setenv("DRY_RUN", "true")
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    publish = respx.put(PUBLISH)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    assert not publish.called


@respx.mock
def test_publish_failure_keeps_the_sent_outcome(env, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    env.setenv("GITHUB_STEP_SUMMARY", str(summary))
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    respx.post(RESEND_URL).mock(return_value=sent(["e1"]))
    respx.put(PUBLISH).mock(return_value=httpx.Response(500))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    report = summary.read_text(encoding="utf-8")
    assert "**Resultado:** enviada para 1 destinatário" in report
    assert "latest edition" in report


SENT_TODAY = "Urubu News — Edição de Segunda — 12/10/2026: Flamengo vence o Fla-Flu"
RUN_SKIPPING = ["run", "--edition", "monday", "--date", "2026-10-14", "--skip-if-sent"]


@respx.mock
def test_skip_if_sent_stops_before_building_when_the_edition_went_out(env, monkeypatch) -> None:
    enable_subscriptions(env)
    monkeypatch.setattr(pipeline, "get_llm_client", lambda settings: pytest.fail("built it"))
    respx.get(PUBLISH).mock(return_value=httpx.Response(200, json={"subject": SENT_TODAY}))
    resend = respx.post(RESEND_URL)

    result = CliRunner().invoke(cli.app, RUN_SKIPPING)

    assert result.exit_code == 0, result.output
    assert not resend.called
    assert "já enviada" in result.output


@respx.mock
def test_skip_if_sent_sends_when_the_last_edition_is_older(env) -> None:
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    older = "Urubu News — Edição de Sexta — 09/10/2026: Outra"
    respx.get(PUBLISH).mock(return_value=httpx.Response(200, json={"subject": older}))
    resend = respx.post(RESEND_URL).mock(return_value=sent(["e1"]))
    respx.put(PUBLISH).mock(return_value=httpx.Response(204))

    result = CliRunner().invoke(cli.app, RUN_SKIPPING)

    assert result.exit_code == 0, result.output
    assert resend.called


@respx.mock
def test_skip_if_sent_sends_when_the_page_is_unreachable(env) -> None:
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    respx.get(PUBLISH).mock(side_effect=httpx.ConnectError("down"))
    resend = respx.post(RESEND_URL).mock(return_value=sent(["e1"]))
    respx.put(PUBLISH).mock(return_value=httpx.Response(204))

    result = CliRunner().invoke(cli.app, RUN_SKIPPING)

    assert result.exit_code == 0, result.output
    assert resend.called


@respx.mock
def test_without_skip_if_sent_a_manual_run_resends(env) -> None:
    enable_subscriptions(env)
    use(env, [ARTICLE], MATCH)
    check = respx.get(PUBLISH).mock(return_value=httpx.Response(200, json={"subject": SENT_TODAY}))
    resend = respx.post(RESEND_URL).mock(return_value=sent(["e1"]))
    respx.put(PUBLISH).mock(return_value=httpx.Response(204))

    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    assert resend.called and not check.called
