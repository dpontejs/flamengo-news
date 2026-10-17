from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time

from flanews.edition import resolve_edition


@freeze_time("2026-10-12 08:00:00")  # Monday
def test_resolve_edition_monday_auto() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    edition = resolve_edition(kind="auto")

    assert edition.kind == "monday"
    assert edition.label == "Edição de Segunda — 12/10/2026"
    assert edition.end == datetime(2026, 10, 12, 8, 0, 0, tzinfo=tz)
    assert edition.start == datetime(2026, 10, 9, 8, 0, 0, tzinfo=tz)  # Previous Friday


@freeze_time("2026-10-16 08:00:00")  # Friday
def test_resolve_edition_friday_auto() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    edition = resolve_edition(kind="auto")

    assert edition.kind == "friday"
    assert edition.label == "Edição de Sexta — 16/10/2026"
    assert edition.end == datetime(2026, 10, 16, 8, 0, 0, tzinfo=tz)
    assert edition.start == datetime(2026, 10, 12, 8, 0, 0, tzinfo=tz)  # Monday of same week


@freeze_time("2026-10-14 14:00:00")  # Wednesday afternoon
def test_resolve_edition_wednesday_auto_fallback() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    edition = resolve_edition(kind="auto")

    # On Wednesday, most recent edition is Monday's
    assert edition.kind == "monday"
    assert edition.label == "Edição de Segunda — 12/10/2026"
    assert edition.end == datetime(2026, 10, 12, 8, 0, 0, tzinfo=tz)
    assert edition.start == datetime(2026, 10, 9, 8, 0, 0, tzinfo=tz)


@freeze_time("2026-10-02 08:00:00")  # Friday October 2nd (start is in September)
def test_resolve_edition_month_boundary() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    edition = resolve_edition(kind="friday")

    assert edition.kind == "friday"
    assert edition.label == "Edição de Sexta — 02/10/2026"
    assert edition.end == datetime(2026, 10, 2, 8, 0, 0, tzinfo=tz)
    assert edition.start == datetime(2026, 9, 28, 8, 0, 0, tzinfo=tz)  # Monday Sep 28th


def test_resolve_match_edition_picks_slot_of_that_day() -> None:
    from datetime import date

    from flanews.edition import resolve_match_edition
    from flanews.schedule import Fixture

    tz = ZoneInfo("America/Sao_Paulo")
    bahia = Fixture(
        match_id="bahia",
        league="bra.1",
        kickoff=datetime(2026, 10, 18, 18, 30, tzinfo=tz),
        time_valid=True,
        state="pre",
        home="Bahia",
        away="Flamengo",
    )
    last_sent = datetime(2026, 10, 16, 19, 11, tzinfo=tz)

    edition = resolve_match_edition("pre", date(2026, 10, 18), [bahia], last_sent)

    assert edition.kind == "pre"
    assert edition.label == "Pré-jogo — 18/10/2026"
    assert (edition.start, edition.end) == (last_sent, datetime(2026, 10, 18, 12, 30, tzinfo=tz))
    assert (edition.match_id, edition.league) == ("bahia", "bra.1")
    post = resolve_match_edition("post", date(2026, 10, 19), [bahia], last_sent)
    assert post.start == edition.end  # window runs from the pre-game send
    assert resolve_match_edition("pre", date(2026, 10, 19), [bahia], last_sent) is None


def test_resolve_match_edition_still_finds_a_slot_already_sent_that_day() -> None:
    from datetime import date

    from flanews.edition import resolve_match_edition

    tz = ZoneInfo("America/Sao_Paulo")
    sent_today = datetime(2026, 10, 26, 8, 5, tzinfo=tz)

    edition = resolve_match_edition("news", date(2026, 10, 26), [], sent_today)

    assert edition.label == "Notícias — 26/10/2026"  # a manual re-run of the same day
