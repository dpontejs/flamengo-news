import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flanews.models import MatchEvent, StandingRow
from flanews.stats.espn import (
    ESPN_SITE_URL,
    ESPN_STANDINGS_URL,
    LEAGUES,
    ESPNStatsClient,
    standings_gap,
)

FIXTURES = Path(__file__).parent / "fixtures" / "espn"
TZ = ZoneInfo("America/Sao_Paulo")
TEAM_ID = 819


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def espn() -> respx.MockRouter:
    with respx.mock(assert_all_called=False) as router:
        for league in LEAGUES:
            schedule = f"{ESPN_SITE_URL}/{league}/teams/{TEAM_ID}/schedule"
            router.get(schedule, params={"fixture": "true"}).mock(
                return_value=httpx.Response(200, json=load(f"fixtures_{league}"))
            )
            router.get(schedule, params={"season": "2026"}).mock(
                return_value=httpx.Response(200, json=load(f"schedule_{league}"))
            )
        router.get(f"{ESPN_SITE_URL}/bra.1/summary", params={"event": "401841269"}).mock(
            return_value=httpx.Response(200, json=load("summary_preview_401841269"))
        )
        router.get(f"{ESPN_SITE_URL}/bra.1/summary", params={"event": "401841263"}).mock(
            return_value=httpx.Response(200, json=load("summary_401841263"))
        )
        router.get(f"{ESPN_SITE_URL}/bra.1/statistics").mock(
            return_value=httpx.Response(200, json=load("league_statistics_bra.1"))
        )
        for league in ("bra.1", "conmebol.libertadores"):
            router.get(f"{ESPN_STANDINGS_URL}/{league}/standings").mock(
                return_value=httpx.Response(200, json=load(f"standings_{league}"))
            )
        yield router


def make_client() -> ESPNStatsClient:
    return ESPNStatsClient(team_id=TEAM_ID, client=httpx.Client())


def test_get_last_match_returns_match_inside_window(espn: respx.MockRouter) -> None:
    match = make_client().get_last_match(
        datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)
    )

    assert match is not None
    assert match.fixture_id == 401841263
    assert match.competition == "Brasileirão"
    assert (match.home, match.home_goals, match.away_goals, match.away) == (
        "Flamengo",
        1,
        0,
        "Fluminense",
    )
    assert match.venue == "Estadio do Maracana"
    assert match.date == datetime(2026, 10, 11, 17, 30, tzinfo=TZ)


def test_get_last_match_translates_statistics(espn: respx.MockRouter) -> None:
    match = make_client().get_last_match(
        datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)
    )

    assert match is not None
    assert match.statistics["Posse de bola"] == ("43.5%", "56.5%")
    assert match.statistics["Finalizações"] == ("17", "12")
    assert "Faltas" in match.statistics
    assert list(match.statistics)[0] == "Posse de bola"


def test_get_last_match_parses_events_and_lineups(espn: respx.MockRouter) -> None:
    match = make_client().get_last_match(
        datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)
    )

    assert match is not None
    goals = [e for e in match.events if e.type == "goal"]
    assert goals == [
        MatchEvent(
            minute=65,
            team="Flamengo",
            player="Jorge Carrascal",
            type="goal",
            detail="Assistência: Lucas Paquetá",
        )
    ]
    late_card = match.events[-1]
    assert (late_card.minute, late_card.extra_minute, late_card.type) == (90, 5, "yellow_card")
    sub = next(e for e in match.events if e.type == "substitution")
    assert sub.player == "Ganso" and sub.detail == "Saiu: Luciano Acosta"
    assert len(match.lineups["Flamengo"]) == 11
    assert match.lineups["Flamengo"][0] == "Agustín Rossi"


def test_get_last_match_without_match_in_window_returns_none(espn: respx.MockRouter) -> None:
    assert (
        make_client().get_last_match(
            datetime(2026, 10, 12, 8, tzinfo=TZ), datetime(2026, 10, 14, 8, tzinfo=TZ)
        )
        is None
    )


def test_get_next_match_picks_earliest_across_competitions(espn: respx.MockRouter) -> None:
    match = make_client().get_next_match(datetime(2026, 10, 14, 12, tzinfo=TZ))

    assert match is not None
    assert match.opponent == "Estudiantes de La Plata"
    assert match.competition == "Libertadores"
    assert match.date == datetime(2026, 10, 15, 21, 30, tzinfo=TZ)
    assert match.is_home is False
    assert match.venue == "Estadio Jorge Luis Hirschi"


def test_get_standings_brasileirao(espn: respx.MockRouter) -> None:
    rows = make_client().get_standings("bra.1")

    assert len(rows) == 20
    leader = rows[0]
    assert (leader.position, leader.team, leader.points, leader.is_flamengo) == (
        1,
        "Flamengo",
        64,
        True,
    )
    assert (leader.played, leader.won, leader.drawn, leader.lost, leader.goals_diff) == (
        30,
        19,
        7,
        4,
        33,
    )


def test_get_standings_libertadores_returns_only_flamengo_group(
    espn: respx.MockRouter,
) -> None:
    rows = make_client().get_standings("conmebol.libertadores")

    assert len(rows) == 4
    assert sum(r.is_flamengo for r in rows) == 1


def test_errors_return_none_or_empty() -> None:
    with respx.mock:
        respx.get(url__startswith="https://site.api.espn.com/").mock(
            return_value=httpx.Response(503)
        )
        client = make_client()
        assert client.get_next_match(datetime(2026, 10, 14, tzinfo=TZ)) is None
        assert (
            client.get_last_match(
                datetime(2026, 10, 9, tzinfo=TZ), datetime(2026, 10, 12, tzinfo=TZ)
            )
            is None
        )
        assert client.get_standings("bra.1") == []


@respx.mock
def test_default_client_uses_user_agent_accepted_by_espn() -> None:
    # ESPN's WAF answers 403 to "flanews/0.1 (+contato@...)", the collectors' User-Agent.
    route = respx.get(url__startswith=ESPN_SITE_URL).mock(
        return_value=httpx.Response(200, json={"events": []})
    )

    ESPNStatsClient().get_next_match(datetime(2026, 10, 14, tzinfo=TZ))

    user_agent = route.calls.last.request.headers["User-Agent"]
    assert user_agent.startswith("flanews/")
    assert "@" not in user_agent


def test_get_last_match_parses_logos(espn: respx.MockRouter) -> None:
    match = make_client().get_last_match(
        datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)
    )

    assert match is not None
    assert match.home_logo == "https://a.espncdn.com/i/teamlogos/soccer/500/819.png"
    assert match.away_logo == "https://a.espncdn.com/i/teamlogos/soccer/500/3445.png"


def test_get_next_match_includes_opponent_logo(espn: respx.MockRouter) -> None:
    match = make_client().get_next_match(datetime(2026, 10, 14, 12, tzinfo=TZ))

    assert match is not None
    assert match.opponent_logo == "https://a.espncdn.com/i/teamlogos/soccer/500/8.png"


def test_get_last_match_parses_leaders(espn: respx.MockRouter) -> None:
    match = make_client().get_last_match(
        datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ)
    )

    assert match is not None
    assert match.leaders["Flamengo"][0] == ("Finalizações", "Samuel Lino", "3")
    assert ("Intervenções defensivas", "Léo Ortiz", "16") in match.leaders["Flamengo"]
    assert match.leaders["Fluminense"][0] == ("Finalizações", "Rodrigo Castillo", "4")


def test_get_standings_includes_goals_for_and_against(espn: respx.MockRouter) -> None:
    leader = make_client().get_standings("bra.1")[0]
    assert (leader.goals_for, leader.goals_against) == (58, 25)


def test_get_moment_form_rankings_and_gap(espn: respx.MockRouter) -> None:
    client = make_client()
    standings = client.get_standings("bra.1")

    moment = client.get_moment(datetime(2026, 10, 12, 8, tzinfo=TZ), standings)

    assert moment is not None
    # Newest first; matches ESPN lastFiveGames (oldest first) plus the Fla-Flu itself.
    assert [f.result for f in moment.form] == ["V", "E", "V", "E", "V"]
    latest = moment.form[0]
    assert (latest.opponent, latest.score, latest.competition) == (
        "Fluminense",
        "1-0",
        "Brasileirão",
    )
    assert moment.standing is not None and moment.standing.points == 64
    assert moment.gap == "1 ponto à frente do Palmeiras"
    goals = [(r.player, r.position, r.value) for r in moment.rankings if r.category == "Gols"]
    assert goals[0] == ("Pedro", 2, 16)
    assert all(r.position <= 10 for r in moment.rankings)
    assists = [r.player for r in moment.rankings if r.category == "Assistências"]
    assert assists[:3] == ["Jorge Carrascal", "Samuel Lino", "Pedro"]


def test_get_moment_reuses_schedules_already_loaded(espn: respx.MockRouter) -> None:
    client = make_client()
    client.get_last_match(datetime(2026, 10, 9, 8, tzinfo=TZ), datetime(2026, 10, 12, 8, tzinfo=TZ))
    calls_before = len(espn.calls)

    client.get_moment(datetime(2026, 10, 12, 8, tzinfo=TZ), [])

    assert len(espn.calls) == calls_before + 1  # only the league statistics


def standing(position: int, team: str, points: int, is_flamengo: bool = False) -> StandingRow:
    return StandingRow(
        position=position,
        team=team,
        points=points,
        played=30,
        won=0,
        drawn=0,
        lost=0,
        goals_diff=0,
        is_flamengo=is_flamengo,
    )


def test_standings_gap_for_leader_chaser_and_tie() -> None:
    assert standings_gap([standing(1, "Flamengo", 64, True), standing(2, "Palmeiras", 60)]) == (
        "4 pontos à frente do Palmeiras"
    )
    assert standings_gap([standing(1, "Palmeiras", 65), standing(2, "Flamengo", 64, True)]) == (
        "1 ponto atrás do líder Palmeiras"
    )
    assert standings_gap([standing(1, "Flamengo", 64, True), standing(2, "Palmeiras", 64)]) == (
        "empatado em pontos com o Palmeiras"
    )
    assert standings_gap([standing(1, "Palmeiras", 65)]) is None


def test_new_competitions_are_tracked() -> None:
    assert LEAGUES["bra.camp.carioca"] == "Carioca"
    assert LEAGUES["bra.supercopa_do_brazil"] == "Supercopa"
    assert LEAGUES["fifa.cwc"] == "Mundial de Clubes"


def test_get_fixtures_parses_state_time_valid_and_kickoff(espn: respx.MockRouter) -> None:
    fixtures = make_client().get_fixtures(datetime(2026, 10, 14, 18, tzinfo=TZ))
    by_id = {f.match_id: f for f in fixtures}

    bahia = by_id["401841269"]
    assert (bahia.league, bahia.state, bahia.time_valid) == ("bra.1", "pre", True)
    assert (bahia.home, bahia.away) == ("Bahia", "Flamengo")
    assert bahia.kickoff == datetime(2026, 10, 18, 18, 30, tzinfo=TZ)
    assert by_id["401912523"].league == "conmebol.libertadores"
    assert by_id["401841263"].state == "post"  # played 3 days before: its post-game may be due
    assert not by_id["401841313"].time_valid
    assert all(f.kickoff >= datetime(2026, 10, 7, 18, tzinfo=TZ) for f in fixtures)
    assert len(by_id) == len(fixtures)


def test_get_fixtures_marks_postponed_matches(espn: respx.MockRouter) -> None:
    data = load("fixtures_bra.1")
    data["events"][0]["competitions"][0]["status"]["type"]["name"] = "STATUS_POSTPONED"
    schedule = f"{ESPN_SITE_URL}/bra.1/teams/{TEAM_ID}/schedule"
    espn.get(schedule, params={"fixture": "true"}).mock(return_value=httpx.Response(200, json=data))

    fixtures = make_client().get_fixtures(datetime(2026, 10, 14, 18, tzinfo=TZ))

    assert next(f for f in fixtures if f.match_id == "401841269").state == "postponed"


def test_get_preview_reads_last_five_and_head_to_head(espn: respx.MockRouter) -> None:
    preview = make_client().get_preview("401841269", "bra.1")

    assert preview.opponent == "Bahia"
    assert [r.result for r in preview.flamengo_form] == ["E", "V", "E", "V", "E"]
    assert preview.flamengo_form[0].opponent == "Estudiantes de La Plata"
    assert [r.result for r in preview.opponent_form] == ["V", "D", "D", "V", "V"]
    assert preview.opponent_form[-1].score == "3-2"  # Bahia's goals first, away at Bragantino
    assert [(r.result, r.score) for r in preview.head_to_head] == [
        ("V", "2-0"),
        ("D", "0-1"),
        ("V", "1-0"),
        ("V", "2-0"),
        ("V", "1-0"),
    ]
    assert preview.head_to_head[0].date.date().isoformat() == "2026-04-19"


def test_get_preview_returns_none_on_error(espn: respx.MockRouter) -> None:
    espn.get(f"{ESPN_SITE_URL}/bra.1/summary", params={"event": "9"}).mock(
        return_value=httpx.Response(500)
    )

    assert make_client().get_preview("9", "bra.1") is None
