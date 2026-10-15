import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from tenacity import wait_none

from flanews.models import Edition, Newsletter
from flanews.send.resend_sender import RESEND_URL, ResendSender, SendError, build_subject

TZ = ZoneInfo("America/Sao_Paulo")
EDITION = Edition(
    kind="monday",
    start=datetime(2026, 10, 9, 8, tzinfo=TZ),
    end=datetime(2026, 10, 12, 8, tzinfo=TZ),
    label="Edição de Segunda — 12/10/2026",
)
FROM = "Flamengo News <news@fla.com>"
UNSUBSCRIBE = "mailto:news@fla.com?subject=Descadastrar"


def make_sender(dry_run: bool = False, api_key: str | None = "re_test") -> ResendSender:
    return ResendSender(
        api_key=api_key,
        sender=FROM,
        recipients=["a@x.com", "b@y.com"],
        dry_run=dry_run,
        client=httpx.Client(),
        wait=wait_none(),
    )


def test_build_subject_with_and_without_headline() -> None:
    with_headline = Newsletter(edition=EDITION, intro="", headline="Flamengo vence o Fla-Flu")
    assert build_subject(with_headline) == (
        "Flamengo News — Edição de Segunda — 12/10/2026: Flamengo vence o Fla-Flu"
    )
    assert build_subject(Newsletter(edition=EDITION, intro="")) == (
        "Flamengo News — Edição de Segunda — 12/10/2026"
    )


@respx.mock
def test_send_posts_payload_with_bcc_and_unsubscribe_header() -> None:
    route = respx.post(RESEND_URL).mock(return_value=httpx.Response(200, json={"id": "email_1"}))

    email_id = make_sender().send("Assunto", "<p>html</p>", "texto", UNSUBSCRIBE)

    assert email_id == "email_1"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer re_test"
    body = json.loads(request.content)
    assert body == {
        "from": FROM,
        "to": ["news@fla.com"],
        "bcc": ["a@x.com", "b@y.com"],
        "subject": "Assunto",
        "html": "<p>html</p>",
        "text": "texto",
        "headers": {"List-Unsubscribe": f"<{UNSUBSCRIBE}>"},
    }


@respx.mock
def test_dry_run_does_not_call_api(caplog) -> None:
    route = respx.post(RESEND_URL)

    with caplog.at_level("INFO"):
        assert make_sender(dry_run=True).send("Assunto", "<p>h</p>", "t", UNSUBSCRIBE) is None

    assert not route.called
    assert "DRY_RUN" in caplog.text and "2 recipients" in caplog.text


def test_send_without_api_key_fails() -> None:
    with pytest.raises(SendError, match="RESEND_API_KEY"):
        make_sender(api_key=None).send("Assunto", "h", "t", UNSUBSCRIBE)


@respx.mock
def test_send_retries_server_errors() -> None:
    route = respx.post(RESEND_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"id": "email_2"})]
    )

    assert make_sender().send("Assunto", "h", "t", UNSUBSCRIBE) == "email_2"
    assert route.call_count == 2


@respx.mock
def test_send_client_error_is_not_retried() -> None:
    route = respx.post(RESEND_URL).mock(
        return_value=httpx.Response(
            422, json={"name": "validation_error", "message": "Invalid `from` field."}
        )
    )

    with pytest.raises(SendError, match="Invalid `from` field"):
        make_sender().send("Assunto", "h", "t", UNSUBSCRIBE)
    assert route.call_count == 1
