from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flanews.config import Settings
from flanews.web.app import create_app
from flanews.web.bolao import BolaoStore
from flanews.web.store import SubscriberStore
from flanews.web.tokens import make_token

SECRET = "s" * 32
API_TOKEN = "t" * 32
NOW = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=3)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class NoMailer:
    def send_confirmation(self, *args) -> None: ...
    def send_edition(self, *args) -> None: ...
    def send_notification(self, *args) -> None: ...


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def stores(tmp_path) -> tuple[SubscriberStore, BolaoStore]:
    path = tmp_path / "db.sqlite"
    subscribers, bolao = SubscriberStore(path), BolaoStore(path)
    bolao.upsert_match("m1", "Bahia", flamengo_home=False, kickoff=KICKOFF)
    return subscribers, bolao


@pytest.fixture
def client(stores, clock) -> TestClient:
    settings = Settings(
        SUBSCRIBE_SECRET=SECRET, SUBSCRIBERS_API_TOKEN=API_TOKEN, PUBLIC_URL="https://news.test"
    )
    subscribers, bolao = stores
    app = create_app(settings, store=subscribers, bolao=bolao, mailer=NoMailer(), now=clock)
    return TestClient(app)


def member(stores, email: str, nickname: str | None = None) -> str:
    subscribers, bolao = stores
    subscribers.request(email, NOW)
    subscribers.confirm(email, NOW)
    if nickname:
        bolao.set_nickname(email, nickname)
    return make_token(SECRET, "bet", email, NOW)


def bet(client, token: str, score: str = "2-1", **extra):
    return client.post("/palpite", data={"t": token, "m": "m1", "p": score, **extra})


def test_bet_get_does_not_record(client, stores) -> None:
    token = member(stores, "ana@x.com", "Ana")

    response = client.get("/palpite", params={"t": token, "m": "m1", "p": "2-1"})

    assert response.status_code == 200
    assert "Flamengo 2 x 1 Bahia" in response.text and "Confirmar" in response.text
    assert stores[1].bet("ana@x.com", "m1") is None


def test_bet_post_records_and_overwrites_before_kickoff(client, stores) -> None:
    token = member(stores, "ana@x.com", "Ana")

    assert bet(client, token, "1-0").status_code == 200
    response = bet(client, token, "3-1")

    assert response.status_code == 200 and "Palpite registrado" in response.text
    assert stores[1].bet("ana@x.com", "m1") == (3, 1)


def test_other_score_form_posts_two_fields(client, stores) -> None:
    token = member(stores, "ana@x.com", "Ana")

    form = client.get("/palpite", params={"t": token, "m": "m1"})
    response = client.post("/palpite", data={"t": token, "m": "m1", "fla": "5", "opp": "0"})

    assert 'name="fla"' in form.text and 'name="opp"' in form.text
    assert response.status_code == 200
    assert stores[1].bet("ana@x.com", "m1") == (5, 0)


def test_bet_after_kickoff_is_rejected(client, stores, clock) -> None:
    token = member(stores, "ana@x.com", "Ana")
    bet(client, token, "1-0")
    clock.now = KICKOFF

    response = bet(client, token, "3-1")
    closed = client.get("/palpite", params={"t": token, "m": "m1", "p": "3-1"})

    assert response.status_code == 409
    assert stores[1].bet("ana@x.com", "m1") == (1, 0)
    assert closed.status_code == 200 and "Bolão fechado" in closed.text
    assert "Flamengo 1 x 0 Bahia" in closed.text


def test_bet_token_cannot_bet_for_someone_else(client, stores) -> None:
    member(stores, "ana@x.com", "Ana")
    bia = member(stores, "bia@x.com", "Bia")

    bet(client, bia, "0-0", email="ana@x.com")
    forged = bet(client, make_token("other", "bet", "ana@x.com", NOW))
    unsubscribe_token = bet(client, make_token(SECRET, "unsubscribe", "ana@x.com", NOW))

    assert stores[1].bet("ana@x.com", "m1") is None
    assert stores[1].bet("bia@x.com", "m1") == (0, 0)
    assert forged.status_code == unsubscribe_token.status_code == 400


def test_first_bet_requires_unique_nickname(client, stores) -> None:
    member(stores, "ana@x.com", "Ana")
    token = member(stores, "bia@x.com")

    form = client.get("/palpite", params={"t": token, "m": "m1", "p": "2-1"})
    without = bet(client, token)
    taken = bet(client, token, nickname="ANA")
    ok = bet(client, token, nickname="Bia")

    assert 'name="nickname"' in form.text
    assert without.status_code == 409 and taken.status_code == 409
    assert 'name="nickname"' in taken.text
    assert ok.status_code == 200 and stores[1].nickname("bia@x.com") == "Bia"


@pytest.mark.parametrize("nickname", ["ab", "x" * 21, "   "])
def test_nickname_length_is_checked(client, stores, nickname) -> None:
    token = member(stores, "bia@x.com")

    assert bet(client, token, nickname=nickname).status_code == 409
    assert stores[1].bet("bia@x.com", "m1") is None


def test_unsubscribed_cannot_bet(client, stores) -> None:
    token = member(stores, "ana@x.com", "Ana")
    stores[0].unsubscribe("ana@x.com", NOW)

    response = bet(client, token)

    assert response.status_code == 403 and "inscrição inativa" in response.text.lower()
    assert stores[1].bet("ana@x.com", "m1") is None


@pytest.mark.parametrize("score", ["9-10", "abc", "-1-0", "2", "2-1-0", ""])
def test_bet_rejects_malformed_score(client, stores, score) -> None:
    token = member(stores, "ana@x.com", "Ana")

    assert bet(client, token, score).status_code == 400
    assert client.get("/palpite", params={"t": token, "m": "m1", "p": score}).status_code in (
        200,  # no score: the "outro placar" form
        400,
    )
    assert stores[1].bet("ana@x.com", "m1") is None


def test_unknown_match_is_404(client, stores) -> None:
    token = member(stores, "ana@x.com", "Ana")

    assert client.get("/palpite", params={"t": token, "m": "nope", "p": "1-0"}).status_code == 404
    assert client.post("/palpite", data={"t": token, "m": "nope", "p": "1-0"}).status_code == 404


def test_nickname_is_escaped(client, stores) -> None:
    token = member(stores, "ana@x.com")
    bet(client, token, nickname="<b>Ana</b>")

    page = client.get("/bolao", params={"t": token})

    assert "&lt;b&gt;Ana&lt;/b&gt;" in page.text and "<b>Ana</b>" not in page.text


def test_ranking_highlights_the_reader(client, stores) -> None:
    ana = member(stores, "ana@x.com", "Ana")
    bia = member(stores, "bia@x.com", "Bia")
    bet(client, ana, "2-1")
    bet(client, bia, "0-0")
    stores[1].summary("m1", (2, 1), persist=True)

    page = client.get("/bolao", params={"t": bia})
    anonymous = client.get("/bolao")

    assert page.status_code == anonymous.status_code == 200
    assert page.text.index("Ana") < page.text.index("Bia")
    assert 'class="me"' in page.text and 'class="me"' not in anonymous.text
    assert "ana@x.com" not in page.text
