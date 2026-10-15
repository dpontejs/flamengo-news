import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flanews.models import (
    Article,
    Brief,
    Edition,
    FormResult,
    MatchEvent,
    MatchStats,
    Newsletter,
    NextMatch,
    PlayerRanking,
    StandingRow,
    TeamMoment,
    Topic,
)
from flanews.render.renderer import FLAMENGO_CREST, render, source_label

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
            home_logo="https://cdn/819.png",
            away_logo="https://cdn/3445.png",
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
            opponent_logo="https://cdn/8.png",
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
    assert re.search(r">\s*1\s*</td>\s*<td[^>]*>\s*x\s*</td>\s*<td[^>]*>\s*0\s*<", html)
    assert re.search(r"65(&#39;|')\s*<strong>Jorge Carrascal</strong>", html)
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


def test_render_scoreboard_with_crests() -> None:
    html, _ = render(full_newsletter())

    assert "🔴" not in html and "⚫" not in html
    assert f'src="{FLAMENGO_CREST}"' in html
    assert 'src="https://cdn/819.png" alt="Flamengo"' in html
    assert 'src="https://cdn/3445.png" alt="Fluminense"' in html
    assert 'src="https://cdn/8.png" alt="Estudiantes de La Plata"' in html


def test_render_without_crests_uses_names_only() -> None:
    newsletter = full_newsletter()
    newsletter.last_match.home_logo = None
    newsletter.last_match.away_logo = None

    html, _ = render(newsletter)

    assert 'alt="Fluminense"' not in html
    assert "Fluminense" in html


def form(result: str, opponent: str, score: str) -> FormResult:
    return FormResult(
        result=result,
        opponent=opponent,
        score=score,
        competition="Brasileirão",
        date=datetime(2026, 10, 11, tzinfo=TZ),
    )


def analysis_newsletter() -> Newsletter:
    newsletter = full_newsletter()
    newsletter.analysis = "Mesmo com menos posse, o Flamengo finalizou mais."
    newsletter.last_match.leaders = {
        "Flamengo": [("Finalizações", "Samuel Lino", "3"), ("Defesas", "Agustín Rossi", "4")]
    }
    newsletter.moment = TeamMoment(
        form=[
            form("V", "Fluminense", "1-0"),
            form("E", "Santos", "2-2"),
            form("D", "Bahia", "0-1"),
        ],
        standing=row(1, "Flamengo", True).model_copy(
            update={"points": 64, "played": 30, "goals_for": 58, "goals_against": 25}
        ),
        gap="1 ponto à frente do Palmeiras",
        rankings=[PlayerRanking(category="Gols", player="Pedro", position=2, value=16)],
    )
    return newsletter


def test_render_analysis_section() -> None:
    html, text = render(analysis_newsletter())

    assert "Análise" in html
    assert "Mesmo com menos posse, o Flamengo finalizou mais." in html
    assert re.search(r">V</td>.*>E</td>.*>D</td>", html, re.S)
    assert "71%" in html  # 64 pts / 90 possíveis
    assert "1 ponto à frente do Palmeiras" in html
    assert "58 gols pró" in html and "25 contra" in html
    assert "Pedro" in html and "2º em gols" in html
    assert "Samuel Lino" in html and "Finalizações" in html

    assert "== Análise ==" in text
    assert "Forma: V E D" in text
    assert "Pedro: 2º em gols (16)" in text


def test_render_analysis_hidden_without_data() -> None:
    html, text = render(full_newsletter())

    assert "Análise" not in html
    assert "Análise" not in text


def test_render_score_uses_separate_cells_for_alignment() -> None:
    # Spans separated by whitespace rendered as "1x0" with a misaligned "x" in Gmail.
    html, _ = render(full_newsletter())

    cells = re.findall(r"<td[^>]*>\s*(1|x|0)\s*</td>", html)
    assert cells[:3] == ["1", "x", "0"]
    score_cell = re.search(r"<td[^>]*>\s*x\s*</td>", html).group(0)
    assert "vertical-align:middle" in score_cell.replace(" ", "")
    assert "padding:0 12px" in score_cell


def briefs_newsletter() -> Newsletter:
    newsletter = full_newsletter()
    newsletter.learn_more = [
        Brief(
            title="FlaBasquete vence na estreia do NBB",
            summary="O time venceu o Minas & segue invicto.",
            url="https://lnb.com.br/1",
            source="google_news:LNB",
            category="Basquete",
        ),
        Brief(
            title="Sesc-Flamengo é campeão",
            summary="",
            url="https://ge.globo.com/v",
            source="ge",
            category="Vôlei",
        ),
    ]
    newsletter.around_brazil = [
        Brief(
            title="Palmeiras chega a 100 gols",
            summary="Marca histórica.",
            url="https://ge.globo.com/p",
            source="ge",
        )
    ]
    return newsletter


def test_render_learn_more_and_around_brazil_sections() -> None:
    html, text = render(briefs_newsletter())

    assert "Saiba mais" in html and "Brasil afora" in html
    assert 'href="https://lnb.com.br/1"' in html
    assert ">Basquete<" in html and ">Vôlei<" in html
    assert "Minas &amp; segue invicto" in html
    assert "Palmeiras chega a 100 gols" in html and "Marca histórica." in html
    order = [html.index(s) for s in ("Notícias", "Saiba mais", "Brasil afora", "Próximo jogo")]
    assert order == sorted(order)

    assert "== Saiba mais ==" in text and "== Brasil afora ==" in text
    assert "[Basquete] FlaBasquete vence na estreia do NBB" in text
    assert "https://lnb.com.br/1" in text
    assert "Minas & segue invicto" in text


def test_render_brief_without_summary_shows_only_title_link() -> None:
    html, _ = render(briefs_newsletter())

    volley = html[
        html.index("Sesc-Flamengo é campeão") - 300 : html.index("Sesc-Flamengo é campeão") + 200
    ]
    assert 'href="https://ge.globo.com/v"' in volley


def test_render_hides_empty_short_sections() -> None:
    html, text = render(full_newsletter())

    assert "Saiba mais" not in html and "Brasil afora" not in html
    assert "Saiba mais" not in text and "Brasil afora" not in text


def test_render_subscribe_link_only_when_given() -> None:
    html, text = render(full_newsletter(), subscribe_url="https://news.test")

    assert 'href="https://news.test"' in html and "Inscreva-se" in html
    assert "https://news.test" in text
    plain_html, plain_text = render(full_newsletter())
    assert "Inscreva-se" not in plain_html and "Inscreva-se" not in plain_text
