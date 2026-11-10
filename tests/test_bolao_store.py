from datetime import UTC, datetime, timedelta

import pytest

from flanews.web.bolao import BolaoStore, points
from flanews.web.store import SubscriberStore

KICKOFF = datetime(2026, 11, 15, 21, 30, tzinfo=UTC)
BEFORE = KICKOFF - timedelta(hours=2)


@pytest.fixture
def subscribers(tmp_path) -> SubscriberStore:
    return SubscriberStore(tmp_path / "db.sqlite")


@pytest.fixture
def bolao(tmp_path, subscribers) -> BolaoStore:
    store = BolaoStore(tmp_path / "db.sqlite")
    store.upsert_match("m1", "Bahia", flamengo_home=False, kickoff=KICKOFF)
    return store


def player(subscribers, bolao, email: str, nickname: str) -> str:
    subscribers.request(email, BEFORE)
    subscribers.confirm(email, BEFORE)
    assert bolao.set_nickname(email, nickname)
    return email


@pytest.mark.parametrize(
    ("bet", "result", "expected"),
    [
        ((2, 1), (2, 1), 5),
        ((3, 2), (2, 1), 3),
        ((1, 0), (2, 1), 3),
        ((2, 0), (2, 1), 2),
        ((0, 0), (2, 1), 0),
        ((0, 0), (0, 0), 5),
        ((1, 1), (0, 0), 2),
        ((1, 0), (0, 0), 0),
        ((0, 2), (1, 3), 3),
    ],
)
def test_points_exact_5_diff_3_outcome_2_miss_0(bet, result, expected) -> None:
    assert points(bet, result) == expected


def test_bet_at_kickoff_is_closed(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")

    assert bolao.is_open("m1", KICKOFF - timedelta(seconds=1))
    assert not bolao.is_open("m1", KICKOFF)
    assert not bolao.place_bet(ana, "m1", (1, 0), KICKOFF)
    assert bolao.bet(ana, "m1") is None


def test_bet_overwrites_before_kickoff(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")

    assert bolao.place_bet(ana, "m1", (1, 0), BEFORE)
    assert bolao.place_bet(ana, "m1", (2, 1), BEFORE)

    assert bolao.bet(ana, "m1") == (2, 1)


def test_result_summary_is_idempotent(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")
    bia = player(subscribers, bolao, "bia@x.com", "Bia")
    bolao.place_bet(ana, "m1", (2, 1), BEFORE)
    bolao.place_bet(bia, "m1", (0, 0), BEFORE)

    first = bolao.summary("m1", (2, 1), persist=True)
    second = bolao.summary("m1", (2, 1), persist=True)

    assert first == second
    assert first.exact == ["Ana"]
    assert [(r.nickname, r.points, r.exact) for r in first.top] == [("Ana", 5, 1), ("Bia", 0, 0)]
    assert bolao.match("m1").fla_goals == 2


def test_summary_without_persist_leaves_the_match_open(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")
    bolao.place_bet(ana, "m1", (2, 1), BEFORE)

    preview = bolao.summary("m1", (2, 1), persist=False)

    assert preview.top[0].points == 5
    assert bolao.match("m1").fla_goals is None
    assert bolao.ranking(2026)[0].points == 0


def test_match_reschedule_moves_the_deadline(bolao) -> None:
    later = KICKOFF + timedelta(days=2)

    bolao.upsert_match("m1", "Bahia", flamengo_home=False, kickoff=later)

    assert bolao.is_open("m1", KICKOFF + timedelta(hours=1))
    assert bolao.match("m1").kickoff == later


def test_unsubscribed_leaves_ranking(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")
    bia = player(subscribers, bolao, "bia@x.com", "Bia")
    bolao.place_bet(ana, "m1", (2, 1), BEFORE)
    bolao.place_bet(bia, "m1", (2, 1), BEFORE)
    subscribers.unsubscribe(bia, BEFORE)

    summary = bolao.summary("m1", (2, 1), persist=True)

    assert [r.nickname for r in summary.top] == ["Ana"]
    assert summary.exact == ["Ana"]


def test_titles_king_and_cold_foot(subscribers, bolao) -> None:
    bets = {"Ana": (2, 1), "Bia": (1, 0), "Caio": (0, 3), "Duda": (0, 1)}
    for nickname, bet in bets.items():
        email = player(subscribers, bolao, f"{nickname.lower()}@x.com", nickname)
        bolao.place_bet(email, "m1", bet, BEFORE)

    summary = bolao.summary("m1", (2, 1), persist=True)

    assert summary.king == "Ana"
    assert summary.cold_foot == "Caio"  # saldo -3 against +1; Duda's -1 misses by less


def test_tied_titles_go_to_nobody(subscribers, bolao) -> None:
    for nickname in ("Ana", "Bia"):
        email = player(subscribers, bolao, f"{nickname.lower()}@x.com", nickname)
        bolao.place_bet(email, "m1", (0, 1), BEFORE)

    summary = bolao.summary("m1", (2, 1), persist=True)

    assert summary.king is None
    assert summary.cold_foot is None


def test_set_nickname_is_unique_case_insensitive(subscribers, bolao) -> None:
    player(subscribers, bolao, "ana@x.com", "Ana")

    assert not bolao.set_nickname("bia@x.com", "ANA")
    assert bolao.set_nickname("ana@x.com", "Aninha")
    assert bolao.nickname("ana@x.com") == "Aninha"


def test_nobody_is_king_with_zero_points(subscribers, bolao) -> None:
    ana = player(subscribers, bolao, "ana@x.com", "Ana")
    bolao.place_bet(ana, "m1", (0, 3), BEFORE)

    summary = bolao.summary("m1", (2, 1), persist=True)

    assert summary.king is None
    assert summary.cold_foot == "Ana"
