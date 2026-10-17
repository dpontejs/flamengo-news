from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

import flanews.__main__ as cli
from flanews.schedule import Fixture
from flanews.send.recipients import LatestEdition
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
    latest = LatestEdition(subject="Urubu News — Novidades: algo", published_at=LAST_SENT)
    monkeypatch.setattr(cli, "_latest", lambda settings: latest)
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


def test_due_does_not_repeat_the_edition_just_sent(calendar) -> None:
    # Sent at 12:31; ESPN then moves the kickoff to 19:00, so the pre-game slot becomes 13:00.
    moved = BAHIA.model_copy(update={"kickoff": datetime(2026, 10, 18, 19, 0, tzinfo=TZ)})
    sent = LatestEdition(
        subject="Urubu News — Pré-jogo — 18/10/2026: Flamengo visita o Bahia",
        published_at=datetime(2026, 10, 18, 12, 31, tzinfo=TZ),
    )
    calendar.setattr(cli, "_fixtures", lambda settings, now: [moved])
    calendar.setattr(cli, "_latest", lambda settings: sent)
    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 13, 5, tzinfo=TZ))

    result = CliRunner().invoke(cli.app, ["due"])

    assert result.stdout == ""


def no_build(*args, **kwargs):
    raise AssertionError("nothing is due: the edition must not be built")


def test_run_auto_without_due_slot_exits_without_building(calendar) -> None:
    from flanews import pipeline

    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 10, 0, tzinfo=TZ))
    calendar.setattr(pipeline, "build_newsletter", no_build)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "auto"])

    assert result.exit_code == 0, result.output
    assert "Nenhuma edição agendada agora" in result.output


def test_run_auto_without_calendar_exits_without_building(calendar) -> None:
    from flanews import pipeline

    def down(settings, now):
        raise StatsUnavailable("espn down")

    calendar.setattr(cli, "_fixtures", down)
    calendar.setattr(pipeline, "build_newsletter", no_build)

    result = CliRunner().invoke(cli.app, ["run", "--edition", "auto"])

    assert result.exit_code == 0, result.output
    assert "Agenda da ESPN indisponível" in result.output


def test_run_auto_resolves_the_due_slot(calendar) -> None:
    from flanews import pipeline

    seen = {}

    def fake_build(edition, settings, **kwargs):
        seen["edition"] = edition
        raise RuntimeError("stop after resolving")

    calendar.setattr(cli, "_now", lambda: datetime(2026, 10, 18, 12, 45, tzinfo=TZ))
    calendar.setattr(pipeline, "build_newsletter", fake_build)

    CliRunner().invoke(cli.app, ["run", "--edition", "auto"])

    assert seen["edition"].label == "Pré-jogo — 18/10/2026"
    assert seen["edition"].match_id == "bahia"


def test_old_fixed_editions_are_gone(calendar) -> None:
    result = CliRunner().invoke(cli.app, ["run", "--edition", "monday"])

    assert result.exit_code == 2
