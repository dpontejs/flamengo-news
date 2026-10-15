from datetime import UTC, datetime, timedelta

from flanews.web.tokens import make_token, read_token

SECRET = "s3cret"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_token_round_trip_returns_the_email() -> None:
    token = make_token(SECRET, "confirm", "ana@example.com", NOW)

    assert read_token(SECRET, "confirm", token, NOW) == "ana@example.com"


def test_token_is_url_safe() -> None:
    token = make_token(SECRET, "unsubscribe", "a+b/c=d@example.com", NOW)

    assert all(c.isalnum() or c in "-_." for c in token)


def test_token_for_another_purpose_is_rejected() -> None:
    token = make_token(SECRET, "confirm", "ana@example.com", NOW)

    assert read_token(SECRET, "unsubscribe", token, NOW) is None


def test_forged_or_tampered_token_is_rejected() -> None:
    token = make_token(SECRET, "confirm", "ana@example.com", NOW)
    other = make_token(SECRET, "confirm", "bob@example.com", NOW)
    email_part = other.split(".")[0]
    tampered = ".".join([email_part, *token.split(".")[1:]])

    assert read_token("other-secret", "confirm", token, NOW) is None
    assert read_token(SECRET, "confirm", tampered, NOW) is None
    assert read_token(SECRET, "confirm", "garbage", NOW) is None
    assert read_token(SECRET, "confirm", "a.b.c", NOW) is None


def test_expired_token_is_rejected_only_when_max_age_is_given() -> None:
    token = make_token(SECRET, "confirm", "ana@example.com", NOW)
    later = NOW + timedelta(days=8)

    assert read_token(SECRET, "confirm", token, later, max_age=timedelta(days=7)) is None
    assert read_token(SECRET, "confirm", token, later) == "ana@example.com"
