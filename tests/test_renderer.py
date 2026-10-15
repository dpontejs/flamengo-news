from datetime import datetime
from zoneinfo import ZoneInfo

from flanews.models import (
    Article,
    Edition,
    MatchEvent,
    MatchStats,
    Newsletter,
    NextMatch,
    StandingRow,
    Topic,
)
from flanews.render.renderer import render, source_label

TZ = ZoneInfo("America/Sao_Paulo")
EDITION = Edition(
    kind="monday",
    start=datetime(2026, 10, 9, 8, tzinfo=TZ),
    end=datetime(2026, 10, 12, 8, tzinfo=TZ),
    label="Edição de Segunda — 12/10/2026",
)


def article(url: str, source: str) -> Article:
    return Article(
        url=url, title="t", source=source, published_at=datetime(2026, 10, 11, tzinfo=TZ)
    )


def row(position: int, team: str, is_flamengo: bool = False) -> StandingRow:
    return StandingRow(
        position=position,
        team=team,
        points=70 - position,
        played=30,
        won=19,
        drawn=7,
        lost=4,
        goals_diff=33,
        is_flamengo=is_flamengo,
    )


def full_newsletter() -> Newsletter:
    return Newsletter(
        edition=EDITION,
        headline="Flamengo vence o Fla-Flu e segue líder",
        intro="Carrascal decidiu o clássico. O time encara o Estudiantes na quinta.",
        topics=[
            Topic(
                title="Vitória no clássico",
                summary="O Flamengo venceu o Fluminense por 1 a 0 & segue líder.",
                importance=5,
                articles=[
                    article("https://ge.globo.com/1", "ge"),
                    article("https://oglobo.globo.com/2", "google_news:O GLOBO"),
                ],
            )
        ],
        last_match=MatchStats(
            fixture_id=1,
            competition="Brasileirão",
            date=datetime(2026, 10, 11, 17, 30, tzinfo=TZ),
            home="Flamengo",
            away="Fluminense",
            home_goals=1,
            away_goals=0,
            venue="Estadio do Maracana",
            events=[
                MatchEvent(
                    minute=65,
                    team="Flamengo",
                    player="Jorge Carrascal",
                    type="goal",
                    detail="Assistência: Lucas Paquetá",
                ),
                MatchEvent(minute=31, team="Flamengo", player="Erick Pulgar", type="yellow_card"),
            ],
            statistics={"Posse de bola": ("43.5%", "56.5%"), "Finalizações": ("17", "12")},
        ),
        next_match=NextMatch(
            opponent="Estudiantes de La Plata",
            competition="Libertadores",
            date=datetime(2026, 10, 15, 21, 30, tzinfo=TZ),
            venue="Estadio Jorge Luis Hirschi",
            is_home=False,
        ),
        standings=[row(i, "Flamengo" if i == 1 else f"Time {i}", i == 1) for i in range(1, 21)],
    )


def test_source_label() -> None:
    assert source_label("google_news:O GLOBO") == "O GLOBO"
    assert source_label("ge") == "ge"
    assert source_label("flamengo_oficial") == "Site oficial"
    assert source_label("google_news") == "Google News"


def test_render_html_contains_all_sections() -> None:
    html, _ = render(full_newsletter(), unsubscribe_url="mailto:news@fla.com?subject=sair")

    assert "Edição de Segunda — 12/10/2026" in html
    assert "Flamengo vence o Fla-Flu e segue líder" in html
    assert "Flamengo 1 x 0 Fluminense" in html
    assert "65&#39; Jorge Carrascal" in html or "65' Jorge Carrascal" in html
    assert "Erick Pulgar" not in html
    assert "Posse de bola" in html and "56.5%" in html
    assert "Vitória no clássico" in html
    assert 'href="https://ge.globo.com/1"' in html
    assert ">O GLOBO</a>" in html
    assert "Estudiantes de La Plata" in html and "15/10 às 21:30" in html
    assert "Time 5" in html and "Time 6" not in html
    assert 'href="mailto:news@fla.com?subject=sair"' in html
    assert "gerado com IA" in html


def test_render_html_escapes_content_and_inlines_css() -> None:
    html, _ = render(full_newsletter())

    assert "1 a 0 &amp; segue" in html
    assert "<style" not in html
    assert 'style="' in html
    assert "#C3281E" in html.upper() or "#c3281e" in html
    assert 'width="600"' in html
    assert html.lower().startswith("<!doctype html>")


def test_render_hides_missing_sections() -> None:
    newsletter = Newsletter(edition=EDITION, intro="Semana sem jogos.")
    html, text = render(newsletter)

    for missing in ("Última partida", "Próximo jogo", "Classificação", "Notícias"):
        assert missing not in html
        assert missing not in text
    assert "Semana sem jogos." in html
    assert "descadastr" not in html


def test_render_text_version() -> None:
    _, text = render(full_newsletter(), unsubscribe_url="mailto:news@fla.com")

    assert "<" not in text
    assert "Flamengo 1 x 0 Fluminense" in text
    assert "65' Jorge Carrascal (Assistência: Lucas Paquetá)" in text
    assert "1 a 0 & segue" in text
    assert "https://ge.globo.com/1" in text
    assert "Estudiantes de La Plata" in text
    assert "1. Flamengo" in text
    assert "mailto:news@fla.com" in text
