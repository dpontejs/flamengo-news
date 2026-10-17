"""When each edition goes out: pre-game, post-game and news slots from the match calendar.

Pure functions (no network): the ESPN client supplies the fixtures and the subscription page
supplies when the last edition was really sent. See docs/features/edicoes-por-jogo.md.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

TZ = ZoneInfo("America/Sao_Paulo")
SEND_TIME = time(8, 0)
PRE_GAME_LEAD = timedelta(hours=6)
EARLY_KICKOFF = time(11, 0)  # before this, the pre-game goes out the night before
NIGHT_BEFORE = time(20, 0)
MIN_NEWS_GAP = timedelta(hours=72)
NEWS_EVERY = timedelta(hours=84)
HORIZON = timedelta(days=14)  # a match further than this does not shape the news yet
WEEKLY_UNTIL = timedelta(days=28)
DEFAULT_WINDOW = timedelta(days=3)  # news window when nothing was ever sent

LABELS = {"pre": "Pré-jogo", "post": "Pós-jogo", "news": "Notícias"}

Kind = Literal["pre", "post", "news"]


class Fixture(BaseModel):
    match_id: str
    league: str
    kickoff: datetime
    time_valid: bool
    state: Literal["pre", "in", "post", "postponed"]
    home: str
    away: str


class Slot(BaseModel):
    kind: Kind
    send_at: datetime
    window_start: datetime
    match_id: str | None = None
    league: str | None = None
    label: str


def _at(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=TZ)


def _pre_game(match: Fixture) -> datetime:
    kickoff = match.kickoff.astimezone(TZ)
    if not match.time_valid:
        return _at(kickoff.date(), SEND_TIME)
    if kickoff.time() < EARLY_KICKOFF:
        return _at(kickoff.date() - timedelta(days=1), NIGHT_BEFORE)
    return max(kickoff - PRE_GAME_LEAD, _at(kickoff.date(), SEND_TIME))


def _post_game(match: Fixture) -> datetime:
    return _at(match.kickoff.astimezone(TZ).date() + timedelta(days=1), SEND_TIME)


def _nearest_send_time(moment: datetime) -> datetime:
    """08:00 of the closest day; a tie goes to the later day."""
    moment = moment.astimezone(TZ)
    same_day = _at(moment.date(), SEND_TIME)
    before, after = (
        (same_day, same_day + timedelta(days=1))
        if moment >= same_day
        else (same_day - timedelta(days=1), same_day)
    )
    return before if moment - before < after - moment else after


def _news_between(start: datetime, end: datetime) -> list[datetime]:
    gap = end - start
    if gap <= MIN_NEWS_GAP:
        return []
    n = max(1, gap // NEWS_EVERY)
    return [_nearest_send_time(start + gap * i / (n + 1)) for i in range(1, n + 1)]


def _mondays(start: datetime, until: datetime) -> list[datetime]:
    first = start + MIN_NEWS_GAP
    day = first.astimezone(TZ).date()
    monday = _at(day + timedelta(days=-day.weekday() % 7), SEND_TIME)
    if monday < first:
        monday += timedelta(days=7)
    days = []
    while monday <= until:
        days.append(monday)
        monday += timedelta(days=7)
    return days


_LABEL_PATTERN = re.compile(rf"(?:{'|'.join(LABELS.values())}) — \d{{2}}/\d{{2}}/\d{{4}}")


def label_of(subject: str) -> str | None:
    """The slot label inside an edition subject ("… — Pré-jogo — 18/10/2026: …")."""
    match = _LABEL_PATTERN.search(subject)
    return match.group(0) if match else None


def _label(kind: Kind, send_at: datetime) -> str:
    return f"{LABELS[kind]} — {send_at.astimezone(TZ):%d/%m/%Y}"


def plan(
    fixtures: list[Fixture],
    now: datetime,
    last_sent: datetime | None,
    sent_label: str | None = None,
) -> list[Slot]:
    """Every slot after the last real send, in order; `window_start` is the previous send.

    `sent_label` is the last edition's label: a reschedule that moves that slot later
    does not make it due again.
    """
    anchor = last_sent or now - DEFAULT_WINDOW
    match_slots: list[tuple[Kind, datetime, Fixture]] = []
    previous_post: datetime | None = None
    for match in sorted(fixtures, key=lambda f: f.kickoff):
        if match.state == "postponed":
            continue
        pre, post = _pre_game(match), _post_game(match)
        # Games on consecutive days: the post-game (with the next match card) wins.
        if previous_post is None or pre > previous_post:
            match_slots.append(("pre", pre, match))
        match_slots.append(("post", post, match))
        previous_post = post
    match_slots.sort(key=lambda slot: slot[1])

    timeline: list[tuple[Kind, datetime, Fixture | None]] = []
    previous = anchor
    for kind, send_at, match in match_slots:
        if send_at <= anchor or _label(kind, send_at) == sent_label:
            previous = max(previous, min(send_at, anchor))
            continue
        if kind == "pre":
            if send_at - previous <= HORIZON:
                news = _news_between(previous, send_at)
            else:
                news = _mondays(previous, min(send_at - MIN_NEWS_GAP, now + WEEKLY_UNTIL))
            timeline += [("news", day, None) for day in news]
        timeline.append((kind, send_at, match))
        previous = send_at
    # After the last known match: weekly news.
    timeline += [("news", day, None) for day in _mondays(previous, now + WEEKLY_UNTIL)]

    slots: list[Slot] = []
    start = anchor
    for kind, send_at, match in timeline:
        slots.append(
            Slot(
                kind=kind,
                send_at=send_at,
                window_start=start,
                match_id=match.match_id if match else None,
                league=match.league if match else None,
                label=_label(kind, send_at),
            )
        )
        start = send_at
    return slots


def due(slots: list[Slot], now: datetime, grace: timedelta = timedelta(hours=3)) -> Slot | None:
    """The latest slot whose send time passed less than `grace` ago."""
    ready = [s for s in slots if s.send_at <= now < s.send_at + grace]
    return max(ready, key=lambda s: s.send_at, default=None)
