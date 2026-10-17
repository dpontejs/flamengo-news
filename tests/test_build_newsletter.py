from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import FakeLLMClient
from pydantic import BaseModel
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews import pipeline
from flanews.config import Settings
from flanews.models import (
    Article,
    Edition,
    FormResult,
    MatchPreview,
    MatchStats,
    Newsletter,
    NextMatch,
    StandingRow,
    TeamMoment,
)
from flanews.summarizer.client import LLMError
from flanews.summarizer.pipeline import (
    AnalysisResponse,
    GroupResponse,
    IntroResponse,
    PreviewResponse,
    SummaryResponse,
)

TZ = ZoneInfo("America/Sao_Paulo")
EDITION = Edition(
    kind="news",
    start=datetime(2026, 10, 9, 8, tzinfo=TZ),
    end=datetime(2026, 10, 12, 8, tzinfo=TZ),
    label="Notícias — 12/10/2026",
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

MOMENT = TeamMoment(gap="1 ponto à frente do Palmeiras")
WIN = FormResult(
    result="V",
    opponent="Bahia",
    score="2-0",
    competition="Brasileiro Serie A",
    date=datetime(2026, 4, 19, tzinfo=TZ),
)
PREVIEW = MatchPreview(opponent="Estudiantes", flamengo_form=[WIN], head_to_head=[WIN])


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

    def get_moment(self, end: datetime, standings: list[StandingRow]) -> TeamMoment | None:
        self.calls["moment"] = (end, standings)
        return MOMENT

    def get_preview(self, match_id: str, league: str):
        self.calls["preview"] = (match_id, league)
        return PREVIEW


def good_llm() -> FakeLLMClient:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is GroupResponse:
            return {"topics": [{"title": "Fla-Flu", "article_ids": [1], "importance": 5}]}
        if schema is SummaryResponse:
            return {"summaries": [{"topic_id": 1, "summary": "O Flamengo venceu."}]}
        if schema is IntroResponse:
            return {"headline": "Flamengo vence", "intro": "Vitória no clássico. Líder."}
        if schema is AnalysisResponse:
            return {"analysis": "Menos posse, mais eficiência."}
        raise AssertionError(schema)

    return FakeLLMClient(respond)


def build(llm: FakeLLMClient, stats: FakeStats | None = None) -> Newsletter:
    return pipeline.build_newsletter(
        EDITION,
        SETTINGS,
        collect=lambda edition, settings: [ARTICLE],
        stats_client=stats or FakeStats(),
        llm=llm,
        candidates=lambda edition, settings: ([], []),
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
    assert newsletter.moment == MOMENT
    assert stats.calls["moment"] == (EDITION.end, STANDINGS)
    assert newsletter.analysis == "Menos posse, mais eficiência."
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

    def fake_build(edition: Edition, settings: Settings, **kwargs) -> Newsletter:
        seen["edition"] = edition
        return newsletter

    monkeypatch.setattr(pipeline, "build_newsletter", fake_build)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.app, ["preview", "--edition", "news", "--date", "2026-10-12"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / "out" / "preview-2026-10-12.html").read_text(encoding="utf-8")
    text = (tmp_path / "out" / "preview-2026-10-12.txt").read_text(encoding="utf-8")
    assert "Flamengo vence" in html and "Abertura." in text
    assert seen["edition"].label == EDITION.label
    assert "preview-2026-10-12.html" in result.output


def test_preview_command_custom_out(monkeypatch, tmp_path) -> None:
    newsletter = Newsletter(edition=EDITION, intro="Abertura.")
    monkeypatch.setattr(pipeline, "build_newsletter", lambda *args, **kwargs: newsletter)

    target = tmp_path / "x" / "minha.html"
    args = ["preview", "--edition", "news", "--date", "2026-10-12", "--out", str(target)]
    result = CliRunner().invoke(cli.app, args)

    assert result.exit_code == 0, result.output
    assert target.exists()
    assert target.with_suffix(".txt").exists()


def test_preview_command_renders_match_stats_bars(monkeypatch, tmp_path) -> None:
    match = MatchStats(
        fixture_id=1,
        competition="Brasileirão",
        date=datetime(2026, 10, 11, 17, 30, tzinfo=EDITION.start.tzinfo),
        home="Flamengo",
        away="Fluminense",
        home_goals=1,
        away_goals=0,
        statistics={"Posse de bola": ("50%", "50%"), "Finalizações": ("10", "8")},
    )
    newsletter = Newsletter(edition=EDITION, intro="Abertura.", last_match=match)
    monkeypatch.setattr(pipeline, "build_newsletter", lambda *args, **kwargs: newsletter)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.app, ["preview", "--edition", "news", "--date", "2026-10-12"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / "out" / "preview-2026-10-12.html").read_text(encoding="utf-8")
    assert "Posse de bola" in html
    assert "Finalizações" in html
    assert "Estatísticas" in html


def test_build_newsletter_analysis_failure_keeps_moment() -> None:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is AnalysisResponse:
            raise LLMError("quota")
        return good_llm().responder(prompt, schema)

    newsletter = build(FakeLLMClient(respond))

    assert newsletter.analysis == ""
    assert newsletter.moment == MOMENT
    assert newsletter.headline == "Flamengo vence"


def test_build_newsletter_without_match_skips_analysis() -> None:
    class NoMatch(FakeStats):
        def get_last_match(self, start, end):
            return None

    llm = good_llm()
    newsletter = build(llm, NoMatch())

    assert newsletter.analysis == ""
    assert not any("Leitura do jogo" in p for p in llm.prompts)


def test_build_newsletter_adds_short_sections_extracting_only_picks() -> None:
    extra = ARTICLE.model_copy(
        update={
            "url": "https://x.com/basquete",
            "title": "FlaBasquete vence",
            "section": "saiba_mais",
            "category": "Basquete",
        }
    )
    other = extra.model_copy(update={"url": "https://x.com/volei", "title": "Vôlei perde"})
    brazil = ARTICLE.model_copy(
        update={"url": "https://ge.globo.com/b", "title": "Palmeiras vence", "section": "brasil"}
    )
    extracted: list[str] = []

    def extract(articles):
        extracted.extend(a.url for a in articles)
        return articles

    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        data = good_llm().responder(prompt, schema)
        if schema is GroupResponse:
            data.update(learn_more_ids=[1], brazil_ids=[1])
        if schema is SummaryResponse:
            data["briefs"] = [
                {"item_id": "S1", "summary": "Estreia com vitória."},
                {"item_id": "B1", "summary": "Segue na cola."},
            ]
        return data

    newsletter = pipeline.build_newsletter(
        EDITION,
        SETTINGS,
        collect=lambda edition, settings: [ARTICLE],
        stats_client=FakeStats(),
        llm=FakeLLMClient(respond),
        candidates=lambda edition, settings: ([extra, other], [brazil]),
        extract=extract,
    )

    assert extracted == ["https://x.com/basquete", "https://ge.globo.com/b"]
    assert [(b.title, b.summary, b.category) for b in newsletter.learn_more] == [
        ("FlaBasquete vence", "Estreia com vitória.", "Basquete")
    ]
    assert [(b.title, b.summary) for b in newsletter.around_brazil] == [
        ("Palmeiras vence", "Segue na cola.")
    ]


def test_collect_candidates_survives_failing_collector(monkeypatch) -> None:
    class Broken:
        def __init__(self, **kwargs):
            pass

        def collect(self, start, end):
            raise RuntimeError("down")

    class Ok(Broken):
        def collect(self, start, end):
            return [ARTICLE.model_copy(update={"section": "brasil"})]

    monkeypatch.setattr(pipeline, "ExtrasCollector", Broken)
    monkeypatch.setattr(pipeline, "BrazilCollector", Ok)

    learn_more, brazil = pipeline.collect_candidates(EDITION, SETTINGS)

    assert learn_more == [] and len(brazil) == 1


def test_preview_command_shows_the_note(monkeypatch, tmp_path) -> None:
    newsletter = Newsletter(edition=EDITION, headline="Flamengo vence", intro="Abertura.")
    monkeypatch.setattr(pipeline, "build_newsletter", lambda *args, **kwargs: newsletter)
    monkeypatch.chdir(tmp_path)
    args = ["preview", "--edition", "news", "--date", "2026-10-12", "--note", "Cara nova."]

    result = CliRunner().invoke(cli.app, args)

    assert result.exit_code == 0, result.output
    html = (tmp_path / "out" / "preview-2026-10-12.html").read_text(encoding="utf-8")
    text = (tmp_path / "out" / "preview-2026-10-12.txt").read_text(encoding="utf-8")
    assert "Cara nova." in html and "Cara nova." in text


def edition(kind: str) -> Edition:
    return Edition(
        kind=kind,
        start=datetime(2026, 10, 19, 8, tzinfo=TZ),
        end=datetime(2026, 10, 22, 15, 30, tzinfo=TZ),
        label=f"{kind} — 22/10/2026",
        match_id="401912521" if kind != "news" else None,
        league="conmebol.libertadores" if kind != "news" else None,
    )


def match_llm(topics: int = 1) -> FakeLLMClient:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is GroupResponse:
            return {
                "topics": [
                    {"title": f"Tópico {i}", "article_ids": [1], "importance": 3}
                    for i in range(topics)
                ]
            }
        if schema is SummaryResponse:
            return {"summaries": [{"topic_id": 1, "summary": "Resumo."}]}
        if schema is IntroResponse:
            return {"headline": "Flamengo encara o Estudiantes", "intro": "Semifinal. Volta."}
        if schema is PreviewResponse:
            return {"lineups": "Flamengo: Rossi; Varela...", "tips": ["ge: Flamengo 2 x 0"]}
        raise AssertionError(f"unexpected call: {schema.__name__}")

    return FakeLLMClient(respond)


def build_kind(kind: str, llm: FakeLLMClient, stats: FakeStats, used: list) -> Newsletter:
    def candidates(edition, settings):
        used.append(edition.kind)
        return [], []

    return pipeline.build_newsletter(
        edition(kind),
        SETTINGS,
        collect=lambda edition, settings: [ARTICLE],
        stats_client=stats,
        llm=llm,
        candidates=candidates,
        match_collect=lambda edition, match, settings: [],
    )


def test_pre_game_builds_preview_without_extras_or_analysis() -> None:
    stats, llm, used = FakeStats(), match_llm(), []

    newsletter = build_kind("pre", llm, stats, used)

    assert newsletter.preview == PREVIEW
    assert stats.calls["preview"] == ("401912521", "conmebol.libertadores")
    assert newsletter.lineups == "Flamengo: Rossi; Varela..."
    assert newsletter.tips == ["ge: Flamengo 2 x 0"]
    assert newsletter.last_match is None and newsletter.analysis == ""
    assert "last" not in stats.calls and used == []
    assert newsletter.next_match == NEXT
    assert len(llm.prompts) <= 4
    assert "O Flamengo venceu." in llm.prompts[-1]  # the preview call reads the article text
    intro = next(p for p in llm.prompts if "abertura" in p)
    assert "Estudiantes" in intro


def test_pre_game_caps_topics_at_four() -> None:
    newsletter = build_kind("pre", match_llm(topics=6), FakeStats(), [])

    assert len(newsletter.topics) == 4


def test_pre_game_without_lineups_or_tips_keeps_the_rest() -> None:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is PreviewResponse:
            raise LLMError("quota")
        return match_llm().responder(prompt, schema)

    newsletter = build_kind("pre", FakeLLMClient(respond), FakeStats(), [])

    assert (newsletter.lineups, newsletter.tips) == ("", [])
    assert newsletter.preview == PREVIEW and newsletter.topics


def test_post_game_has_no_extras() -> None:
    stats, used = FakeStats(), []

    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is AnalysisResponse:
            return {"analysis": "Leitura."}
        return match_llm().responder(prompt, schema)

    newsletter = build_kind("post", FakeLLMClient(respond), stats, used)

    assert used == [] and newsletter.last_match == MATCH and newsletter.analysis == "Leitura."
    assert newsletter.preview is None


def test_news_has_extras() -> None:
    used = []

    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is AnalysisResponse:
            return {"analysis": "Leitura."}
        return match_llm().responder(prompt, schema)

    build_kind("news", FakeLLMClient(respond), FakeStats(), used)

    assert used == ["news"]


def test_pre_game_with_only_the_preview_is_not_empty() -> None:
    newsletter = Newsletter(edition=edition("pre"), intro="", next_match=NEXT, preview=PREVIEW)

    assert not pipeline.is_empty(newsletter)
    assert pipeline.is_empty(Newsletter(edition=edition("news"), intro=""))


TIP = Article(
    url="https://ge.globo.com/palpite",
    title="Palpites para Bahia x Flamengo",
    source="google_news:ge",
    published_at=datetime(2026, 10, 16, 20, tzinfo=TZ),
    content="Comentarista: Flamengo 2 x 1. " + "x" * 3000 + " Bahia: Marcos Felipe; Gilberto...",
)


def test_pre_game_preview_reads_match_articles_first_and_whole() -> None:
    llm = match_llm()

    pipeline.build_newsletter(
        edition("pre"),
        SETTINGS,
        collect=lambda edition, settings: [ARTICLE],
        stats_client=FakeStats(),
        llm=llm,
        candidates=lambda edition, settings: ([], []),
        match_collect=lambda edition, match, settings: [TIP],
    )

    preview = llm.prompts[-1]
    assert preview.index("Palpites para Bahia x Flamengo") < preview.index("O Flamengo venceu.")
    assert "Bahia: Marcos Felipe" in preview  # the second line-up sits far into the text


def test_collect_match_articles_searches_the_match_in_the_last_three_days(monkeypatch) -> None:
    seen = {}

    def fake_collect(edition, settings, collectors):
        seen["window"] = (edition.start, edition.end)
        seen["urls"] = [c.rss_url for c in collectors]
        return [TIP]

    monkeypatch.setattr(pipeline, "collect_articles", fake_collect)
    away = NEXT.model_copy(update={"opponent": "Bahia", "is_home": False})

    articles = pipeline.collect_match_articles(edition("pre"), away, SETTINGS)

    assert articles == [TIP]
    end = edition("pre").end
    assert seen["window"] == (end - timedelta(days=3), end)
    assert any("q=Bahia+Flamengo+palpite&" in u for u in seen["urls"])
    assert any("Bahia+x+Flamengo%22+escala%C3%A7%C3%A3o" in u for u in seen["urls"])
    assert any("Bahia+x+Flamengo%22+onde+assistir" in u for u in seen["urls"])
    assert not any("Palpite+ge" in u for u in seen["urls"])  # NEXT is a Libertadores match


def test_collect_match_articles_adds_the_round_tips_for_brasileirao(monkeypatch) -> None:
    seen = {}

    def fake_collect(edition, settings, collectors):
        seen["urls"] = [c.rss_url for c in collectors]
        return []

    monkeypatch.setattr(pipeline, "collect_articles", fake_collect)
    league = NEXT.model_copy(update={"opponent": "Bahia", "competition": "Brasileirão"})

    pipeline.collect_match_articles(edition("pre"), league, SETTINGS)

    assert any("q=%22Palpite+ge%22&" in u for u in seen["urls"])


def test_pre_game_keeps_outlook_and_where_to_watch() -> None:
    def respond(prompt: str, schema: type[BaseModel]) -> dict:
        if schema is PreviewResponse:
            return {
                "lineups": "Bahia: Ronaldo; Gilberto\nFlamengo: Rossi; Varela\nDesfalques: Danilo",
                "tips": [],
                "outlook": "Jogo equilibrado na Fonte Nova.",
                "broadcast": "Premiere (pay-per-view)",
            }
        return match_llm().responder(prompt, schema)

    llm = FakeLLMClient(respond)
    newsletter = build_kind("pre", llm, FakeStats(), [])

    assert newsletter.outlook == "Jogo equilibrado na Fonte Nova."
    assert newsletter.broadcast == "Premiere (pay-per-view)"
    assert newsletter.lineups.splitlines() == [
        "Flamengo: Rossi; Varela",
        "Bahia: Ronaldo; Gilberto",
        "Desfalques: Danilo",
    ]
    preview_prompt = llm.prompts[-1]
    assert "Últimos confrontos" in preview_prompt and "2-0 Bahia" in preview_prompt
