from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from flanews.models import Edition
from flanews.schedule import TZ, Fixture, Kind, Slot, plan


def resolve_edition(
    kind: Literal["monday", "friday", "auto"] = "auto",
    now: datetime | None = None,
    tz_name: str = "America/Sao_Paulo",
) -> Edition:
    """Resolve the temporal window and metadata for a newsletter edition.

    - Monday edition: Friday 08:00 -> Monday 08:00 (covers weekend match).
    - Friday edition: Monday 08:00 -> Friday 08:00 (covers midweek match).
    - Auto mode:
      - Monday (weekday 0) -> monday edition
      - Friday (weekday 4) -> friday edition
      - Tue, Wed, Thu -> most recent monday edition
      - Sat, Sun -> most recent friday edition
    """
    tz = ZoneInfo(tz_name)
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    weekday = now.weekday()  # Monday=0, Tuesday=1, ..., Sunday=6

    if kind == "auto":
        if weekday in (0, 1, 2, 3):
            resolved_kind: Literal["monday", "friday"] = "monday"
        else:
            resolved_kind = "friday"
    else:
        resolved_kind = kind

    if resolved_kind == "monday":
        # Calculate target Monday (current or most recent)
        days_back = (weekday - 0) % 7
        target_date = now.date() - timedelta(days=days_back)
        end = datetime.combine(target_date, time(8, 0, 0), tzinfo=tz)
        start = end - timedelta(days=3)  # Previous Friday 08:00
        label = f"Edição de Segunda — {target_date.strftime('%d/%m/%Y')}"
    else:
        # Calculate target Friday (current or most recent)
        days_back = (weekday - 4) % 7
        target_date = now.date() - timedelta(days=days_back)
        end = datetime.combine(target_date, time(8, 0, 0), tzinfo=tz)
        start = end - timedelta(days=4)  # Monday 08:00 of the same week
        label = f"Edição de Sexta — {target_date.strftime('%d/%m/%Y')}"

    return Edition(
        kind=resolved_kind,
        start=start,
        end=end,
        label=label,
    )


def edition_from_slot(slot: Slot) -> Edition:
    return Edition(
        kind=slot.kind,
        start=slot.window_start,
        end=slot.send_at,
        label=slot.label,
        match_id=slot.match_id,
        league=slot.league,
    )


def resolve_match_edition(
    kind: Kind, day: date, fixtures: list[Fixture], last_sent: datetime | None
) -> Edition | None:
    """The `kind` slot planned for `day`, or None.

    A send made on `day` itself is ignored, so a manual re-run of that day still finds its slot.
    """
    start_of_day = datetime.combine(day, time(0, 0), tzinfo=TZ)
    anchor = last_sent if last_sent is not None and last_sent < start_of_day else None
    slots = plan(fixtures, start_of_day, anchor)
    slot = next((s for s in slots if s.kind == kind and s.send_at.date() == day), None)
    return edition_from_slot(slot) if slot else None
