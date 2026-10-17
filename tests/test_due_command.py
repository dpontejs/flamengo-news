from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews.schedule import Fixture
from flanews.stats.espn import StatsUnavailable

TZ = ZoneInfo("America/Sao_Paulo")
BAHIA = Fixture(
    match_id="bahia",
    league="bra.1",
    kickoff=datetime(2026, 10, 18, 18, 30, tzinfo=TZ),
    time_valid=True,
    state="pre",
    home="Bahia",
    away="Flamengo",
)
LAST_SENT = datetime(2026, 10, 16, 19, 11, tzinfo=TZ)


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(cli, "_fixtures", lambda settings, now: [BAHIA])
    monkeypatch.setattr(cli, "_last_sent", lambda settings: LAST_SENT)
    return monkeypatch


def test_due_prints_the_due_slot(calendar) -> None:
    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 12, 45, tzinfo=TZ))
    result = CliRunner().invoke(cli.app, ["due"])

    assert result.exit_code == 0, result.output
    assert result.stdout == "pre\t2026-10-18\tPré-jogo — 18/10/2026\n"


def test_due_prints_nothing_when_nothing_is_due(calendar) -> None:
    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 10, 0, tzinfo=TZ))
    result = CliRunner().invoke(cli.app, ["due"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""


def test_due_prints_nothing_when_espn_fails(calendar) -> None:
    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 12, 45, tzinfo=TZ))

    def down(settings, now):
        raise StatsUnavailable("espn down")

    calendar.setattr(cli, "_fixtures", down)

    result = CliRunner().invoke(cli.app, ["due"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""


def test_run_pre_without_slot_that_day_exits_1(calendar) -> None:
    result = CliRunner().invoke(cli.app, ["run", "--edition", "pre", "--date", "2026-10-20"])

    assert result.exit_code == 1
    assert "Nenhuma edição Pré-jogo prevista em 20/10/2026" in result.output
