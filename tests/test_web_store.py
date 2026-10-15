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
