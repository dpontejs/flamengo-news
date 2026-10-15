from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from flanews.config import Settings
from flanews.web.app import create_app
from flanews.web.mailer import MailError
from flanews.web.store import SubscriberStore
from flanews.web.tokens import make_token, read_token

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SECRET = "test-secret"
API_TOKEN = "api-token"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    def send_confirmation(self, email: str, confirm_url: str) -> None:
        if self.fail:
            raise MailError("Resend is down")
        self.sent.append((email, confirm_url))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path) -> SubscriberStore:
    return SubscriberStore(tmp_path / "subscribers.db")


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(store, mailer, clock) -> TestClient:
    settings = Settings(
        SUBSCRIBE_SECRET=SECRET,
        SUBSCRIBERS_API_TOKEN=API_TOKEN,
        PUBLIC_URL="https://news.test",
    )
    return TestClient(create_app(settings, store=store, mailer=mailer, now=clock))


def token_from(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def subscribe(client: TestClient, email: str = "ana@example.com", **extra) -> object:
    return client.post("/subscribe", data={"email": email, "website": "", **extra})


def test_landing_page_has_the_form(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'action="/subscribe"' in response.text
    assert "segunda e sexta" in response.text


def test_subscribe_creates_pending_and_sends_confirmation(client, store, mailer) -> None:
    response = subscribe(client, " Ana@Example.com ")

    assert response.status_code == 200
    assert "Confira seu e-mail" in response.text
    assert store.get("ana@example.com").status == "pending"
    [(email, url)] = mailer.sent
    assert email == "ana@example.com"
    assert url.startswith("https://news.test/confirm?token=")
    assert read_token(SECRET, "confirm", token_from(url), NOW) == "ana@example.com"


def test_subscribe_same_page_for_active_email(client, store, mailer) -> None:
    store.request("ana@example.com", NOW)
    store.confirm("ana@example.com", NOW)
    new = subscribe(client, "bob@example.com").text

    response = subscribe(client, "ana@example.com")

    assert response.status_code == 200
    assert response.text.replace("ana@example.com", "bob@example.com") == new
    assert [email for email, _ in mailer.sent] == ["bob@example.com"]


def test_subscribe_honeypot_sends_nothing(client, store, mailer) -> None:
    response = subscribe(client, website="http://spam.example")

    assert response.status_code == 200
    assert store.get("ana@example.com") is None
    assert mailer.sent == []


@pytest.mark.parametrize("email", ["", "ana", "ana@", "@example.com", "a b@example.com"])
def test_subscribe_invalid_email_sends_nothing(client, store, mailer, email) -> None:
    response = subscribe(client, email)

    assert response.status_code == 400
    assert "e-mail válido" in response.text
    assert mailer.sent == []


def test_subscribe_rate_limited_per_ip(client, mailer) -> None:
    for i in range(5):
        assert subscribe(client, f"user{i}@example.com").status_code == 200

    response = subscribe(client, "user5@example.com")

    assert response.status_code == 429
    assert len(mailer.sent) == 5


def test_confirmation_resend_cooldown(client, mailer, clock) -> None:
    subscribe(client)
    subscribe(client)
    clock.now = NOW + timedelta(minutes=11)
    subscribe(client)

    assert len(mailer.sent) == 2


def test_mail_failure_shows_error_and_allows_retry(client, mailer) -> None:
    mailer.fail = True
    response = subscribe(client)

    assert response.status_code == 502
    mailer.fail = False
    assert subscribe(client).status_code == 200
    assert len(mailer.sent) == 1


def test_confirm_activates_and_is_idempotent(client, store, mailer) -> None:
    subscribe(client)
    url = mailer.sent[0][1]

    first = client.get(f"/confirm?token={token_from(url)}")
    second = client.get(f"/confirm?token={token_from(url)}")

    assert first.status_code == second.status_code == 200
    assert "Inscrição confirmada" in first.text
    assert store.active() == ["ana@example.com"]


def test_confirm_rejects_expired_or_forged_token(client, store, mailer, clock) -> None:
    subscribe(client)
    token = token_from(mailer.sent[0][1])
    forged = make_token("other-secret", "confirm", "ana@example.com", NOW)

    clock.now = NOW + timedelta(days=8)
    assert client.get(f"/confirm?token={token}").status_code == 400
    assert client.get(f"/confirm?token={forged}").status_code == 400
    assert client.get("/confirm").status_code == 400
    assert store.active() == []


def test_confirm_valid_token_for_unknown_email_fails(client) -> None:
    token = make_token(SECRET, "confirm", "ghost@example.com", NOW)

    assert client.get(f"/confirm?token={token}").status_code == 400


def active(store: SubscriberStore, email: str = "ana@example.com") -> str:
    store.request(email, NOW)
    store.confirm(email, NOW)
    return make_token(SECRET, "unsubscribe", email, NOW)


def test_unsubscribe_get_does_not_unsubscribe(client, store) -> None:
    token = active(store)

    response = client.get(f"/unsubscribe?token={token}")

    assert response.status_code == 200
    assert 'method="post"' in response.text
    assert store.active() == ["ana@example.com"]


def test_unsubscribe_post_unsubscribes(client, store) -> None:
    token = active(store)

    response = client.post(f"/unsubscribe?token={token}")

    assert response.status_code == 200
    assert "descadastrado" in response.text
    assert store.active() == []


def test_one_click_post_unsubscribes(client, store) -> None:
    token = active(store)

    response = client.post(f"/unsubscribe?token={token}", data={"List-Unsubscribe": "One-Click"})

    assert response.status_code == 200
    assert store.active() == []


def test_unsubscribe_rejects_invalid_token(client, store) -> None:
    active(store)
    confirm_token = make_token(SECRET, "confirm", "ana@example.com", NOW)

    assert client.post(f"/unsubscribe?token={confirm_token}").status_code == 400
    assert client.get("/unsubscribe?token=garbage").status_code == 400
    assert store.active() == ["ana@example.com"]


def test_api_subscribers_requires_token(client, store) -> None:
    active(store)

    assert client.get("/api/subscribers").status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert client.get("/api/subscribers", headers=wrong).status_code == 401


def test_api_subscribers_lists_only_active_with_unsubscribe_links(client, store) -> None:
    active(store, "ana@example.com")
    store.request("pending@example.com", NOW)
    active(store, "gone@example.com")
    store.unsubscribe("gone@example.com", NOW)

    response = client.get("/api/subscribers", headers={"Authorization": f"Bearer {API_TOKEN}"})

    assert response.status_code == 200
    [item] = response.json()
    assert item["email"] == "ana@example.com"
    assert item["unsubscribe_url"].startswith("https://news.test/unsubscribe?token=")
    token = token_from(item["unsubscribe_url"])
    assert read_token(SECRET, "unsubscribe", token, NOW) == "ana@example.com"


def test_api_subscribers_disabled_without_configured_token(store, mailer, clock) -> None:
    settings = Settings(SUBSCRIBE_SECRET=SECRET, PUBLIC_URL="https://news.test")
    client = TestClient(create_app(settings, store=store, mailer=mailer, now=clock))

    response = client.get("/api/subscribers", headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_health(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_app_refuses_to_start_without_secret(store, mailer) -> None:
    with pytest.raises(RuntimeError, match="SUBSCRIBE_SECRET"):
        create_app(Settings(), store=store, mailer=mailer)


def test_version_reports_the_build_commit(store, mailer, monkeypatch) -> None:
    monkeypatch.setenv("GIT_SHA", "abc123")
    app = create_app(Settings(SUBSCRIBE_SECRET=SECRET), store=store, mailer=mailer)

    response = TestClient(app).get("/version.json")

    assert response.json() == {"commit": "abc123"}
    assert response.headers["cache-control"] == "no-store"


def test_get_subscribe_goes_back_to_the_form(client) -> None:
    # Reloading the "check your inbox" page (or a link preview) issues a GET.
    response = client.get("/subscribe", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_head_on_pages_for_link_previews(client) -> None:
    assert client.head("/").status_code == 200


def test_favicon_points_to_the_crest(client) -> None:
    response = client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code in (301, 302, 307, 308)
    assert response.headers["location"].endswith("/819.png")
