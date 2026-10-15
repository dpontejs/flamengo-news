from datetime import datetime
from zoneinfo import ZoneInfo

from fakes import FakeLLMClient
from pydantic import BaseModel
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews import pipeline
from flanews.config import Settings
from flanews.models import Article, Edition, MatchStats, Newsletter, NextMatch, StandingRow
from flanews.summarizer.client import LLMError
from flanews.summarizer.pipeline import GroupResponse, IntroResponse, SummaryResponse

TZ = ZoneInfo("America/Sao_Paulo")
EDITION = Edition(
    kind="monday",
    start=datetime(2026, 10, 9, 8, tzinfo=TZ),
    end=datetime(2026, 10, 12, 8, tzinfo=TZ),
    label="Edição de Segunda — 12/10/2026",
)
SETTINGS = Settings(NEWSLETTER_FROM="Flamengo News <news@fla.com>", GEMINI_API_KEY="k")
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
NEXT = NextMatch(
    opponent="Estudiantes", competition="Libertadores", date=datetime(2026, 10, 15, tzinfo=TZ)
)
STANDINGS = [
    StandingRow(
        position=1,
        team="Flamengo",
        points=64,
        played=30,
        won=19,
        drawn=7,
        lost=4,
        goals_diff=33,
        is_flamengo=True,
    )
]


class FakeStats:
    def __init__(self) -> None:
        self.calls: dict = {}

    def get_last_match(self, start: datetime, end: datetime) -> MatchStats | None:
        self.calls["last"] = (start, end)
        return MATCH

    def get_next_match(self, now: datetime) -> NextMatch | None:
        self.calls["next"] = now
        return NEXT

    def get_standings(self, league: str = "bra.1") -> list[StandingRow]:
        return STANDINGS


def good_llm() -> FakeLLMClient:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is GroupResponse:
            return {"topics": [{"title": "Fla-Flu", "article_ids": [1], "importance": 5}]}
        if schema is SummaryResponse:
            return {"summaries": [{"topic_id": 1, "summary": "O Flamengo venceu."}]}
        if schema is IntroResponse:
            return {"headline": "Flamengo vence", "intro": "Vitória no clássico. Líder."}
        raise AssertionError(schema)

    return FakeLLMClient(respond)


def build(llm: FakeLLMClient, stats: FakeStats | None = None) -> Newsletter:
    return pipeline.build_newsletter(
        EDITION,
        SETTINGS,
        collect=lambda edition, settings: [ARTICLE],
        stats_client=stats or FakeStats(),
        llm=llm,
    )


def test_build_newsletter_combines_news_stats_and_summary() -> None:
    stats = FakeStats()
    llm = good_llm()
    newsletter = build(llm, stats)

    assert newsletter.edition == EDITION
    assert newsletter.headline == "Flamengo vence"
    assert newsletter.intro == "Vitória no clássico. Líder."
    assert [t.title for t in newsletter.topics] == ["Fla-Flu"]
    assert newsletter.last_match == MATCH
    assert newsletter.next_match == NEXT
    assert newsletter.standings == STANDINGS
    assert stats.calls["last"] == (EDITION.start, EDITION.end)
    assert stats.calls["next"] == EDITION.end
    assert "Flamengo 1 x 0 Fluminense" in llm.prompts[-1]


def test_build_newsletter_survives_llm_failure() -> None:
    def broken(prompt: str, schema: type[BaseModel]) -> dict:
        raise LLMError("quota")

    newsletter = build(FakeLLMClient(broken))

    assert newsletter.topics == []
    assert newsletter.intro == ""
    assert newsletter.last_match == MATCH


def test_unsubscribe_url_uses_sender_address() -> None:
    assert pipeline.unsubscribe_url(SETTINGS) == "mailto:news@fla.com?subject=Descadastrar"


def test_preview_command_writes_html_and_text(monkeypatch, tmp_path) -> None:
    newsletter = Newsletter(edition=EDITION, headline="Flamengo vence", intro="Abertura.")
    seen = {}

    def fake_build(edition: Edition, settings: Settings) -> Newsletter:
        seen["edition"] = edition
        return newsletter

    monkeypatch.setattr(pipeline, "build_newsletter", fake_build)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.app, ["preview", "--edition", "monday", "--date", "2026-10-14"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / "out" / "preview-2026-10-12.html").read_text(encoding="utf-8")
    text = (tmp_path / "out" / "preview-2026-10-12.txt").read_text(encoding="utf-8")
    assert "Flamengo vence" in html and "Abertura." in text
    assert seen["edition"].label == EDITION.label
    assert "preview-2026-10-12.html" in result.output


def test_preview_command_custom_out(monkeypatch, tmp_path) -> None:
    newsletter = Newsletter(edition=EDITION, intro="Abertura.")
    monkeypatch.setattr(pipeline, "build_newsletter", lambda edition, settings: newsletter)

    target = tmp_path / "x" / "minha.html"
    result = CliRunner().invoke(cli.app, ["preview", "--out", str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists()
    assert target.with_suffix(".txt").exists()
