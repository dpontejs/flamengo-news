from datetime import datetime
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews.models import MatchEvent, MatchStats, NextMatch, StandingRow
from flanews.stats.table import standings_window

TZ = ZoneInfo("America/Sao_Paulo")


def row(position: int, team: str = "", is_flamengo: bool = False) -> StandingRow:
    return StandingRow(
        position=position,
        team=team or f"Time {position}",
        points=70 - position,
        played=30,
        won=10,
        drawn=5,
        lost=15,
        goals_diff=0,
        is_flamengo=is_flamengo,
    )


def test_standings_window_centers_on_flamengo() -> None:
    rows = [row(i, is_flamengo=i == 8) for i in range(1, 21)]
    assert [r.position for r in standings_window(rows)] == [6, 7, 8, 9, 10]


def test_standings_window_clamps_at_table_edges() -> None:
    top = [row(i, is_flamengo=i == 1) for i in range(1, 21)]
    bottom = [row(i, is_flamengo=i == 20) for i in range(1, 21)]
    assert [r.position for r in standings_window(top)] == [1, 2, 3, 4, 5]
    assert [r.position for r in standings_window(bottom)] == [16, 17, 18, 19, 20]


def test_standings_window_without_flamengo_is_empty() -> None:
    assert standings_window([row(1), row(2)]) == []


class FakeStatsClient:
    calls: dict = {}

    def get_last_match(self, start: datetime, end: datetime) -> MatchStats | None:
        FakeStatsClient.calls["last"] = (start, end)
        return MatchStats(
            fixture_id=1,
            competition="Brasileirão",
            date=datetime(2026, 10, 11, 17, 30, tzinfo=TZ),
            home="Flamengo",
            away="Fluminense",
            home_goals=1,
            away_goals=0,
            venue="Maracanã",
            events=[
                MatchEvent(minute=65, team="Flamengo", player="Jorge Carrascal", type="goal"),
                MatchEvent(minute=31, team="Flamengo", player="Pulgar", type="yellow_card"),
            ],
            statistics={"Posse de bola": ("43.5%", "56.5%")},
        )

    def get_next_match(self, now: datetime) -> NextMatch | None:
        FakeStatsClient.calls["next"] = now
        return NextMatch(
            opponent="Estudiantes de La Plata",
            competition="Libertadores",
            date=datetime(2026, 10, 15, 21, 30, tzinfo=TZ),
            venue="Estadio Jorge Luis Hirschi",
            is_home=False,
        )

    def get_standings(self, league: str = "bra.1") -> list[StandingRow]:
        return [row(i, "Flamengo" if i == 1 else "", is_flamengo=i == 1) for i in range(1, 21)]


def test_stats_command_prints_match_next_and_table(monkeypatch) -> None:
    monkeypatch.setattr(cli, "ESPNStatsClient", lambda **kwargs: FakeStatsClient())

    result = CliRunner().invoke(cli.app, ["stats", "--edition", "news", "--date", "2026-10-12"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Flamengo 1 x 0 Fluminense" in out
    assert "65' Jorge Carrascal" in out
    assert "Pulgar" not in out  # only goals are listed
    assert "Posse de bola" in out and "43.5%" in out
    assert "Estudiantes de La Plata" in out and "15/10 21:30" in out and "fora" in out
    assert "Time 5" in out and "Time 6" not in out
    start, end = FakeStatsClient.calls["last"]
    assert (start.day, end.day) == (9, 12)
    assert FakeStatsClient.calls["next"] == end


def test_stats_command_without_data(monkeypatch) -> None:
    class Empty(FakeStatsClient):
        def get_last_match(self, start, end):
            return None

        def get_next_match(self, now):
            return None

        def get_standings(self, league="bra.1"):
            return []

    monkeypatch.setattr(cli, "ESPNStatsClient", lambda **kwargs: Empty())

    result = CliRunner().invoke(cli.app, ["stats", "--edition", "news", "--date", "2026-10-12"])

    assert result.exit_code == 0, result.output
    assert "Nenhuma partida" in result.output
