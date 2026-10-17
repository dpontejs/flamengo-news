from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flanews.schedule import Fixture, Slot, due, plan

TZ = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")


def at(day: str, hour: str = "08:00") -> datetime:
    return datetime.strptime(f"{day} {hour}", "%d/%m/%Y %H:%M").replace(tzinfo=TZ)


def fixture(
    kickoff: datetime, match_id: str = "1", time_valid: bool = True, state: str = "pre"
) -> Fixture:
    return Fixture(
        match_id=match_id,
        league="bra.1",
        kickoff=kickoff,
        time_valid=time_valid,
        state=state,
        home="Flamengo",
        away="Rival",
    )


def until_last_match(slots: list[Slot]) -> list[Slot]:
    """Drop the weekly news planned after the last known match."""
    last = max(i for i, s in enumerate(slots) if s.kind == "post")
    return slots[: last + 1]


def summary(slots: list[Slot]) -> list[tuple[str, str]]:
    return [(s.kind, s.send_at.astimezone(TZ).strftime("%d/%m %H:%M")) for s in slots]


OCTOBER = [
    fixture(datetime(2026, 10, 18, 21, 30, tzinfo=UTC), "bahia"),
    fixture(datetime(2026, 10, 23, 0, 30, tzinfo=UTC), "estudiantes"),
    fixture(datetime(2026, 10, 26, 23, 0, tzinfo=UTC), "atletico"),
    fixture(datetime(2026, 10, 29, 23, 0, tzinfo=UTC), "vasco"),
    fixture(datetime(2026, 11, 4, 22, 30, tzinfo=UTC), "gremio"),
    fixture(datetime(2026, 11, 18, 20, 0, tzinfo=UTC), "athletico", time_valid=False),
]
NOW = at("17/10/2026", "12:00")
LAST_SENT = at("16/10/2026", "19:11")


def test_plan_matches_the_real_october_calendar() -> None:
    slots = plan(OCTOBER, NOW, LAST_SENT)

    assert summary(slots) == [
        ("pre", "18/10 12:30"),
        ("post", "19/10 08:00"),
        ("news", "21/10 08:00"),
        ("pre", "22/10 15:30"),
        ("post", "23/10 08:00"),
        ("news", "25/10 08:00"),
        ("pre", "26/10 14:00"),
        ("post", "27/10 08:00"),
        ("pre", "29/10 14:00"),
        ("post", "30/10 08:00"),
        ("news", "02/11 08:00"),
        ("pre", "04/11 13:30"),
        ("post", "05/11 08:00"),
        ("news", "08/11 08:00"),
        ("news", "12/11 08:00"),
        ("news", "15/11 08:00"),
        ("pre", "18/11 08:00"),
        ("post", "19/11 08:00"),
    ]
    assert slots[0].label == "Pré-jogo — 18/10/2026"
    assert slots[1].label == "Pós-jogo — 19/10/2026"
    assert slots[2].label == "Notícias — 21/10/2026"
    assert (slots[0].match_id, slots[0].league) == ("bahia", "bra.1")
    assert slots[2].match_id is None


@pytest.mark.parametrize(
    ("kickoff", "expected"),
    [
        (at("25/10/2026", "10:00"), ("pre", "24/10 20:00")),
        (at("25/10/2026", "12:00"), ("pre", "25/10 08:00")),
        (at("25/10/2026", "16:00"), ("pre", "25/10 10:00")),
    ],
)
def test_pre_game_never_before_8am_and_morning_kickoff_goes_the_night_before(
    kickoff, expected
) -> None:
    slots = plan([fixture(kickoff)], at("23/10/2026"), at("23/10/2026"))

    assert summary(slots)[0] == expected


def test_tbd_kickoff_gets_pre_game_at_8am_on_match_day() -> None:
    slots = plan([fixture(at("25/10/2026", "16:00"), time_valid=False)], NOW, LAST_SENT)

    assert [s for s in summary(slots) if s[0] != "news"][0] == ("pre", "25/10 08:00")


def test_postponed_match_has_no_slots() -> None:
    match = fixture(at("19/10/2026", "20:00"), state="postponed")

    assert all(s.match_id != match.match_id for s in plan([match], NOW, LAST_SENT))


def test_no_news_when_gap_is_72h_or_less() -> None:
    games = [fixture(at("18/10/2026", "20:00"), "a"), fixture(at("21/10/2026", "20:00"), "b")]

    kinds = [k for k, _ in summary(until_last_match(plan(games, NOW, LAST_SENT)))]

    assert kinds == ["pre", "post", "pre", "post"]


def test_long_gap_spreads_news_evenly() -> None:
    games = [fixture(at("18/10/2026", "20:00"), "a"), fixture(at("31/10/2026", "20:00"), "b")]

    news = [d for k, d in summary(until_last_match(plan(games, NOW, LAST_SENT))) if k == "news"]

    # 19/10 08:00 -> 31/10 14:00 is 294 h: 3 editions, one every ~73.5 h
    assert news == ["22/10 08:00", "25/10 08:00", "28/10 08:00"]


def test_no_fixtures_means_weekly_monday_news() -> None:
    news = summary(plan([], NOW, LAST_SENT))

    assert news == [("news", "26/10 08:00"), ("news", "02/11 08:00"), ("news", "09/11 08:00")]


def test_window_starts_at_previous_send() -> None:
    slots = plan(OCTOBER, NOW, LAST_SENT)

    assert slots[0].window_start == LAST_SENT
    assert all(b.window_start == a.send_at for a, b in zip(slots, slots[1:], strict=False))


def test_utc_midnight_kickoff_uses_local_date() -> None:
    slots = plan([OCTOBER[1]], at("20/10/2026"), at("20/10/2026"))

    assert summary(slots)[:2] == [("pre", "22/10 15:30"), ("post", "23/10 08:00")]


def test_due_returns_slot_only_inside_grace_window() -> None:
    slots = plan(OCTOBER, NOW, LAST_SENT)

    assert due(slots, at("18/10/2026", "12:29")) is None
    assert due(slots, at("18/10/2026", "12:30")).label == "Pré-jogo — 18/10/2026"
    assert due(slots, at("18/10/2026", "15:29")).label == "Pré-jogo — 18/10/2026"
    assert due(slots, at("18/10/2026", "15:30")) is None


def test_due_ignores_slots_before_last_send() -> None:
    # The pre-game went out at 12:31; a reschedule must not make it due again.
    sent = at("18/10/2026", "12:31")
    slots = plan(OCTOBER, at("18/10/2026", "13:00"), sent)

    assert due(slots, at("18/10/2026", "13:00")) is None
    assert slots[0].kind == "post" and slots[0].window_start == sent


def test_due_picks_the_latest_when_two_are_inside_the_window() -> None:
    late = Slot(kind="news", send_at=at("21/10/2026", "09:00"), window_start=NOW, label="b")
    early = Slot(kind="post", send_at=at("21/10/2026", "08:00"), window_start=NOW, label="a")

    assert due([early, late], at("21/10/2026", "09:30")) == late


def test_now_defaults_to_last_sent_window_start_when_never_sent() -> None:
    slots = plan(OCTOBER[:1], NOW, None)

    assert slots[0].window_start == NOW - timedelta(days=3)


def test_weekly_news_after_the_last_known_match() -> None:
    games = [fixture(at("18/10/2026", "20:00"))]

    news = [d for k, d in summary(plan(games, NOW, LAST_SENT)) if k == "news"]

    assert news == ["26/10 08:00", "02/11 08:00", "09/11 08:00"]
