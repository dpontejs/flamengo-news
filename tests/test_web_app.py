from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from flanews.config import Settings
from flanews.send.resend_sender import UNSUBSCRIBE_PLACEHOLDER
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
        self.editions: list[tuple[str, str, str, str, str]] = []
        self.fail = False
        self.fail_editions = False

    def send_confirmation(self, email: str, confirm_url: str) -> None:
        if self.fail:
            raise MailError("Resend is down")
        self.sent.append((email, confirm_url))

    def send_edition(
        self, email: str, subject: str, html: str, text: str, unsubscribe_url: str
    ) -> None:
        if self.fail_editions:
            raise MailError("Resend is down")
        self.editions.append((email, subject, html, text, unsubscribe_url))


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
    assert "antes e depois de cada jogo" in response.text.lower()
    assert "segunda e sexta" not in response.text.lower()


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


@pytest.mark.parametrize(
    "email",
    [
        "",
        "ana",
        "ana@",
        "@example.com",
        "a b@example.com",
        "<script>alert(1)</script>@x.com",
        "ana@example",
        "ana@exa_mple.com",
        "ana@@example.com",
        "ana@example..com",
    ],
)
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


def test_favicon_points_to_the_icon(client) -> None:
    response = client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code in (301, 302, 307, 308)
    assert response.headers["location"] == "/static/icon-512.png"


AUTH = {"Authorization": f"Bearer {API_TOKEN}"}
EDITION = {
    "subject": "Flamengo News — Edição de Segunda",
    "html": f'<p>Fla</p><a href="{UNSUBSCRIBE_PLACEHOLDER}">sair</a>',
    "text": f"Fla\nSair: {UNSUBSCRIBE_PLACEHOLDER}",
}


def confirm_new_subscriber(client, mailer, email: str = "ana@example.com"):
    subscribe(client, email)
    token = token_from(mailer.sent[-1][1])
    return client.get(f"/confirm?token={token}")


def test_publish_latest_edition_requires_token(client, store) -> None:
    assert client.put("/api/latest-edition", json=EDITION).status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert client.put("/api/latest-edition", json=EDITION, headers=wrong).status_code == 401
    assert store.latest_edition() is None


def test_publish_latest_edition_requires_unsubscribe_placeholder(client, store) -> None:
    edition = {**EDITION, "html": "<p>sem link de descadastro</p>"}

    response = client.put("/api/latest-edition", json=edition, headers=AUTH)

    assert response.status_code == 422
    assert store.latest_edition() is None


def test_first_confirmation_sends_the_latest_edition(client, mailer) -> None:
    assert client.put("/api/latest-edition", json=EDITION, headers=AUTH).status_code == 204

    response = confirm_new_subscriber(client, mailer)

    assert response.status_code == 200
    assert "última edição" in response.text
    [(email, subject, html, text, unsubscribe_url)] = mailer.editions
    assert email == "ana@example.com"
    assert subject == "Boas-vindas! Flamengo News — Edição de Segunda"
    assert (html, text) == (EDITION["html"], EDITION["text"])
    token = token_from(unsubscribe_url)
    assert unsubscribe_url.startswith("https://news.test/unsubscribe?token=")
    assert read_token(SECRET, "unsubscribe", token, NOW) == "ana@example.com"


def test_clicking_the_confirmation_link_again_does_not_resend(client, mailer) -> None:
    client.put("/api/latest-edition", json=EDITION, headers=AUTH)
    subscribe(client)
    url = f"/confirm?token={token_from(mailer.sent[0][1])}"

    client.get(url)
    second = client.get(url)

    assert second.status_code == 200
    assert len(mailer.editions) == 1


def test_confirmation_without_published_edition_sends_nothing(client, mailer) -> None:
    response = confirm_new_subscriber(client, mailer)

    assert response.status_code == 200
    assert "última edição" not in response.text
    assert mailer.editions == []


def test_edition_failure_keeps_the_subscription(client, store, mailer) -> None:
    client.put("/api/latest-edition", json=EDITION, headers=AUTH)
    mailer.fail_editions = True

    response = confirm_new_subscriber(client, mailer)

    assert response.status_code == 200
    assert "Inscrição confirmada" in response.text
    assert "última edição" not in response.text
    assert store.active() == ["ana@example.com"]


@pytest.mark.parametrize("name", ["logo-email.png", "icon-512.png", "og-image.png"])
def test_static_logo_files_are_served(client, name) -> None:
    response = client.get(f"/static/{name}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_page_uses_the_brand_not_the_crest(client) -> None:
    html = client.get("/").text

    assert "<title>Urubu News</title>" in html
    assert '<meta property="og:image" content="https://news.test/static/og-image.png">' in html
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html
    assert '<meta property="og:site_name" content="Urubu News">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert 'rel="icon" href="/static/icon-512.png"' in html
    assert "URUBU" in html and "FLAMENGO" not in html
    assert "sem ligação oficial com o clube" in html
    # The crest only appears as match data, in the sample scoreboard.
    assert html.count("819.png") == 1


@pytest.mark.parametrize(
    "email", ["ped.x@duck.com", "a.b+tag@sub.example.com.br", "kyw_9@outlook.com"]
)
def test_subscribe_accepts_common_addresses(client, mailer, email) -> None:
    assert subscribe(client, email).status_code == 200
    assert mailer.sent[-1][0] == email


def test_daily_cap_on_confirmation_emails(client, store, mailer, monkeypatch) -> None:
    # Many IPs could otherwise use the page to e-mail random addresses and burn the quota.
    monkeypatch.setattr("flanews.web.app.CONFIRMATIONS_PER_DAY", 3)
    for i in range(3):
        store.request(f"user{i}@example.com", NOW)

    response = subscribe(client, "late@example.com")

    assert response.status_code == 429
    assert mailer.sent == []
    assert store.get("late@example.com") is None


def test_page_explains_what_is_stored(client) -> None:
    html = client.get("/").text

    assert "Privacidade" in html
    assert "só o seu e-mail" in html


def test_latest_edition_subject_requires_token(client) -> None:
    assert client.get("/api/latest-edition").status_code == 401


def test_latest_edition_subject_is_404_until_published(client) -> None:
    assert client.get("/api/latest-edition", headers=AUTH).status_code == 404


def test_latest_edition_subject_after_publishing(client) -> None:
    client.put("/api/latest-edition", json=EDITION, headers=AUTH)

    response = client.get("/api/latest-edition", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "subject": EDITION["subject"],
        "published_at": NOW.isoformat(),
        "text": EDITION["text"],
    }
