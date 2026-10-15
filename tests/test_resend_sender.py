import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from tenacity import wait_none

from flanews.models import Edition, Newsletter
from flanews.send.recipients import Recipient
from flanews.send.resend_sender import (
    RESEND_BATCH_URL,
    UNSUBSCRIBE_PLACEHOLDER,
    ResendSender,
    SendError,
    build_subject,
)

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
        dry_run=dry_run,
        client=httpx.Client(),
        wait=wait_none(),
    )


ANA = Recipient("ana@x.com", "https://news.test/unsubscribe?token=ANA")
BOB = Recipient("bob@y.com", UNSUBSCRIBE)
HTML = f'<p>html</p><a href="{UNSUBSCRIBE_PLACEHOLDER}">sair</a>'
TEXT = f"texto\nSair: {UNSUBSCRIBE_PLACEHOLDER}"


def ok(count: int) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": f"email_{i}"} for i in range(count)]})


def test_build_subject_with_and_without_headline() -> None:
    with_headline = Newsletter(edition=EDITION, intro="", headline="Flamengo vence o Fla-Flu")
    assert build_subject(with_headline) == (
        "Urubu News — Edição de Segunda — 12/10/2026: Flamengo vence o Fla-Flu"
    )
    assert build_subject(Newsletter(edition=EDITION, intro="")) == (
        "Urubu News — Edição de Segunda — 12/10/2026"
    )


@respx.mock
def test_sender_batches_one_email_per_recipient_with_own_unsubscribe_link() -> None:
    route = respx.post(RESEND_BATCH_URL).mock(return_value=ok(2))

    ids = make_sender().send("Assunto", HTML, TEXT, [ANA, BOB])

    assert ids == ["email_0", "email_1"]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer re_test"
    assert request.headers["Idempotency-Key"]
    ana, bob = json.loads(request.content)
    assert ana == {
        "from": FROM,
        "to": ["ana@x.com"],
        "subject": "Assunto",
        "html": '<p>html</p><a href="https://news.test/unsubscribe?token=ANA">sair</a>',
        "text": "texto\nSair: https://news.test/unsubscribe?token=ANA",
        "headers": {
            "List-Unsubscribe": "<https://news.test/unsubscribe?token=ANA>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    assert bob["to"] == ["bob@y.com"]
    assert bob["headers"] == {"List-Unsubscribe": f"<{UNSUBSCRIBE}>"}
    assert UNSUBSCRIBE in bob["html"] and UNSUBSCRIBE_PLACEHOLDER not in bob["html"]


@respx.mock
def test_unsubscribe_link_is_html_escaped() -> None:
    route = respx.post(RESEND_BATCH_URL).mock(return_value=ok(1))

    make_sender().send("A", HTML, TEXT, [Recipient("c@z.com", "https://n.test/u?a=1&b=2")])

    [email] = json.loads(route.calls.last.request.content)
    assert 'href="https://n.test/u?a=1&amp;b=2"' in email["html"]
    assert email["text"].endswith("https://n.test/u?a=1&b=2")


@respx.mock
def test_send_splits_into_batches_of_100() -> None:
    route = respx.post(RESEND_BATCH_URL).mock(side_effect=[ok(100), ok(50)])
    recipients = [Recipient(f"u{i}@x.com", UNSUBSCRIBE) for i in range(150)]

    ids = make_sender().send("Assunto", HTML, TEXT, recipients)

    assert len(ids) == 150
    sizes = [len(json.loads(call.request.content)) for call in route.calls]
    assert sizes == [100, 50]
    keys = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert len(keys) == 2


@respx.mock
def test_send_without_recipients_sends_nothing() -> None:
    route = respx.post(RESEND_BATCH_URL)

    assert make_sender().send("Assunto", HTML, TEXT, []) == []
    assert not route.called


@respx.mock
def test_dry_run_does_not_call_api(caplog) -> None:
    route = respx.post(RESEND_BATCH_URL)

    with caplog.at_level("INFO"):
        assert make_sender(dry_run=True).send("Assunto", HTML, TEXT, [ANA, BOB]) == []

    assert not route.called
    assert "DRY_RUN" in caplog.text and "2 recipients" in caplog.text


def test_send_without_api_key_fails() -> None:
    with pytest.raises(SendError, match="RESEND_API_KEY"):
        make_sender(api_key=None).send("Assunto", HTML, TEXT, [ANA])


@respx.mock
def test_send_retries_server_errors_with_the_same_idempotency_key() -> None:
    route = respx.post(RESEND_BATCH_URL).mock(side_effect=[httpx.Response(503), ok(1)])

    assert make_sender().send("Assunto", HTML, TEXT, [ANA]) == ["email_0"]
    assert route.call_count == 2
    first, second = (call.request.headers["Idempotency-Key"] for call in route.calls)
    assert first == second


@respx.mock
def test_send_client_error_is_not_retried() -> None:
    route = respx.post(RESEND_BATCH_URL).mock(
        return_value=httpx.Response(
            422, json={"name": "validation_error", "message": "Invalid `from` field."}
        )
    )

    with pytest.raises(SendError, match="Invalid `from` field"):
        make_sender().send("Assunto", HTML, TEXT, [ANA])
    assert route.call_count == 1


@respx.mock
def test_failure_after_a_sent_batch_says_how_many_went_out() -> None:
    respx.post(RESEND_BATCH_URL).mock(
        side_effect=[ok(100), httpx.Response(422, json={"message": "bad"})]
    )
    recipients = [Recipient(f"u{i}@x.com", UNSUBSCRIBE) for i in range(120)]

    with pytest.raises(SendError, match="100 of 120"):
        make_sender().send("Assunto", HTML, TEXT, recipients)
