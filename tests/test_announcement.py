import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews.config import get_settings
from flanews.render.announcement import Announcement, parse_announcement, render_announcement
from flanews.send.resend_sender import RESEND_BATCH_URL as RESEND_URL
from flanews.send.resend_sender import UNSUBSCRIBE_PLACEHOLDER

SOURCE = """# Urubu News de cara nova

Olá, **rubro-negro**!

A newsletter mudou:
- **Pré-jogo** no dia da partida;
- **Pós-jogo** na manhã seguinte.

Até amanhã.
"""


def test_parse_reads_subject_paragraphs_and_lists() -> None:
    announcement = parse_announcement(SOURCE)

    assert announcement.subject == "Urubu News de cara nova"
    assert announcement.blocks == [
        ["Olá, **rubro-negro**!"],
        ["A newsletter mudou:"],
        ["- **Pré-jogo** no dia da partida;", "- **Pós-jogo** na manhã seguinte."],
        ["Até amanhã."],
    ]


def test_parse_requires_a_subject_line() -> None:
    with pytest.raises(ValueError, match="# "):
        parse_announcement("Sem assunto.\n")


def test_render_formats_bold_and_lists_and_escapes_html() -> None:
    announcement = Announcement(subject="Aviso", blocks=[["Fla <b>x</b> **Bahia**"], ["- um"]])

    html, text = render_announcement(announcement, unsubscribe_url="https://u/1")

    assert "Fla &lt;b&gt;x&lt;/b&gt; <strong>Bahia</strong>" in html
    assert "<li" in html and ">um</li>" in html
    assert "https://u/1" in html
    assert "Fla <b>x</b> Bahia" in text and "- um" in text and "**" not in text
    assert "https://u/1" in text


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("NEWSLETTER_FROM", "Urubu News <news@fla.com>")
    monkeypatch.setenv("NEWSLETTER_RECIPIENTS", "a@x.com")
    get_settings.cache_clear()
    source = tmp_path / "aviso.md"
    source.write_text(SOURCE, encoding="utf-8")
    yield source
    get_settings.cache_clear()


@respx.mock
def test_announce_sends_to_recipients_without_publishing_an_edition(env, tmp_path) -> None:
    route = respx.post(RESEND_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "e1"}]})
    )
    page = respx.put(url__regex=r".*/api/latest-edition")

    result = CliRunner().invoke(cli.app, ["announce", str(env)])

    assert result.exit_code == 0, result.output
    [body] = json.loads(route.calls.last.request.content)
    assert body["subject"] == "Urubu News de cara nova"
    assert body["to"] == ["a@x.com"]
    assert "<strong>rubro-negro</strong>" in body["html"]
    assert UNSUBSCRIBE_PLACEHOLDER not in body["html"]
    assert body["headers"]["List-Unsubscribe"] == "<mailto:news@fla.com?subject=Descadastrar>"
    assert not page.called  # the schedule and new subscribers only see real editions
    assert (tmp_path / "out" / "aviso.html").exists()
    assert "enviado para 1 destinatário" in result.output


@respx.mock
def test_announce_dry_run_sends_nothing(env, monkeypatch) -> None:
    monkeypatch.setenv("DRY_RUN", "true")
    get_settings.cache_clear()
    route = respx.post(RESEND_URL)

    result = CliRunner().invoke(cli.app, ["announce", str(env)])

    assert result.exit_code == 0, result.output
    assert not route.called
    assert "não enviado (DRY_RUN)" in result.output
