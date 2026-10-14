from datetime import UTC, datetime

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


def test_models_instantiation() -> None:
    now = datetime.now(UTC)
    article = Article(
        url="https://ge.globo.com/flamengo/noticia/1",
        title="Flamengo vence clássico",
        source="ge",
        published_at=now,
    )
    topic = Topic(title="Clássico", summary="Resumo", articles=[article], importance=5)
    match_event = MatchEvent(
        minute=45, team="Flamengo", player="Arrascaeta", type="Goal", detail="Normal Goal"
    )
    match = MatchStats(
        fixture_id=1,
        competition="Brasileirão",
        date=now,
        home="Flamengo",
        away="Vasco",
        home_goals=2,
        away_goals=0,
        events=[match_event],
        statistics={"Posse de bola": ("60%", "40%")},
        lineups={"Flamengo": ["Rossi", "Varela"]},
    )
    next_match = NextMatch(
        opponent="Palmeiras", competition="Libertadores", date=now, is_home=False
    )
    standing = StandingRow(
        position=1,
        team="Flamengo",
        points=60,
        played=28,
        won=18,
        drawn=6,
        lost=4,
        goals_diff=25,
        is_flamengo=True,
    )
    edition = Edition(kind="monday", start=now, end=now, label="Edição de Segunda")
    newsletter = Newsletter(
        edition=edition,
        intro="Resumo da rodada",
        topics=[topic],
        last_match=match,
        next_match=next_match,
        standings=[standing],
    )

    assert newsletter.topics[0].articles[0].title == "Flamengo vence clássico"
    assert newsletter.last_match.home_goals == 2
    assert newsletter.standings[0].is_flamengo is True
