from datetime import UTC, datetime, timedelta

import pytest

from flanews.web.store import RequestResult, SubscriberStore

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path) -> SubscriberStore:
    return SubscriberStore(tmp_path / "subscribers.db")


def test_new_email_is_pending_and_gets_a_confirmation(store: SubscriberStore) -> None:
    assert store.request("  Ana@Example.com ", NOW) is RequestResult.SEND_CONFIRMATION

    subscriber = store.get("ana@example.com")
    assert subscriber is not None
    assert subscriber.status == "pending"
    assert store.active() == []


def test_confirmation_is_not_resent_within_cooldown(store: SubscriberStore) -> None:
    store.request("ana@example.com", NOW)

    assert store.request("ana@example.com", NOW + timedelta(minutes=5)) is RequestResult.COOLDOWN
    assert (
        store.request("ana@example.com", NOW + timedelta(minutes=11))
        is RequestResult.SEND_CONFIRMATION
    )


def test_confirm_activates_and_is_idempotent(store: SubscriberStore) -> None:
    store.request("ana@example.com", NOW)

    assert store.confirm("ana@example.com", NOW) is True
    assert store.confirm("ana@example.com", NOW + timedelta(hours=1)) is True
    assert store.active() == ["ana@example.com"]
    assert store.request("ana@example.com", NOW) is RequestResult.ALREADY_ACTIVE


def test_confirm_unknown_email_fails(store: SubscriberStore) -> None:
    assert store.confirm("ninguem@example.com", NOW) is False


def test_unsubscribe_removes_from_active_list(store: SubscriberStore) -> None:
    store.request("ana@example.com", NOW)
    store.confirm("ana@example.com", NOW)

    store.unsubscribe("ana@example.com", NOW)

    assert store.active() == []
    assert store.get("ana@example.com").status == "unsubscribed"


def test_old_confirmation_link_does_not_undo_an_unsubscribe(store: SubscriberStore) -> None:
    store.request("ana@example.com", NOW)
    store.confirm("ana@example.com", NOW)
    store.unsubscribe("ana@example.com", NOW)

    assert store.confirm("ana@example.com", NOW) is False
    assert store.active() == []


def test_resubscribe_after_unsubscribe_requires_confirmation(store: SubscriberStore) -> None:
    store.request("ana@example.com", NOW)
    store.confirm("ana@example.com", NOW)
    store.unsubscribe("ana@example.com", NOW)

    assert store.request("ana@example.com", NOW) is RequestResult.SEND_CONFIRMATION
    assert store.get("ana@example.com").status == "pending"
    assert store.confirm("ana@example.com", NOW) is True


def test_data_survives_reopening_the_database(tmp_path) -> None:
    path = tmp_path / "nested" / "subscribers.db"
    first = SubscriberStore(path)
    first.request("ana@example.com", NOW)
    first.confirm("ana@example.com", NOW)

    assert SubscriberStore(path).active() == ["ana@example.com"]


def test_latest_edition_is_empty_until_published(store: SubscriberStore) -> None:
    assert store.latest_edition() is None


def test_publishing_an_edition_replaces_the_previous_one(tmp_path) -> None:
    store = SubscriberStore(tmp_path / "subscribers.db")
    store.set_latest_edition("Antiga", "<p>a</p>", "a", NOW)
    store.set_latest_edition("Nova", "<p>n</p>", "n", NOW + timedelta(days=4))

    edition = SubscriberStore(tmp_path / "subscribers.db").latest_edition()

    assert (edition.subject, edition.html, edition.text) == ("Nova", "<p>n</p>", "n")


def test_confirmations_sent_since_counts_recent_requests(store: SubscriberStore) -> None:
    store.request("old@example.com", NOW - timedelta(days=2))
    store.request("a@example.com", NOW - timedelta(hours=3))
    store.request("b@example.com", NOW)

    assert store.confirmations_sent_since(NOW - timedelta(days=1)) == 2


def test_purge_removes_stale_pending_and_old_unsubscribed(store: SubscriberStore) -> None:
    old = NOW - timedelta(days=31)
    store.request("stale@example.com", old)
    store.request("gone@example.com", old)
    store.confirm("gone@example.com", old)
    store.unsubscribe("gone@example.com", old)
    store.request("recent-out@example.com", NOW)
    store.confirm("recent-out@example.com", NOW)
    store.unsubscribe("recent-out@example.com", NOW)
    store.request("fan@example.com", old)
    store.confirm("fan@example.com", old)

    removed = store.purge(NOW)

    assert removed == 2
    assert store.get("stale@example.com") is None and store.get("gone@example.com") is None
    assert store.get("recent-out@example.com").status == "unsubscribed"
    assert store.active() == ["fan@example.com"]
