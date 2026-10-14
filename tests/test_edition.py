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
