"""From a planned slot to the edition it builds (window, label, match)."""

from datetime import date, datetime, time

from flanews.models import Edition
from flanews.schedule import TZ, Fixture, Kind, Slot, plan


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
