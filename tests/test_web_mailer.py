import json

import httpx
import pytest
import respx

from flanews.web.mailer import MailError, ResendConfirmationMailer

URL = "https://news.test/confirm?token=abc.def.ghi"


def mailer() -> ResendConfirmationMailer:
    return ResendConfirmationMailer(
        api_key="re_test", sender="Flamengo News <news@example.com>", public_url="https://news.test"
    )


@respx.mock
def test_sends_confirmation_email_with_link() -> None:
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "e1"})
    )

    mailer().send_confirmation("ana@example.com", URL)

    payload = json.loads(route.calls.last.request.content)
    assert route.calls.last.request.headers["Authorization"] == "Bearer re_test"
    assert payload["to"] == ["ana@example.com"]
    assert payload["from"] == "Flamengo News <news@example.com>"
    assert "Confirme" in payload["subject"]
    assert URL in payload["html"] and URL in payload["text"]


@respx.mock
def test_resend_error_raises_mail_error() -> None:
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(422, json={"message": "invalid"})
    )

    with pytest.raises(MailError, match="invalid"):
        mailer().send_confirmation("ana@example.com", URL)


@respx.mock
def test_network_error_raises_mail_error() -> None:
    respx.post("https://api.resend.com/emails").mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(MailError):
        mailer().send_confirmation("ana@example.com", URL)


@respx.mock
def test_sends_the_edition_with_the_subscriber_unsubscribe_link() -> None:
    from flanews.send.resend_sender import RESEND_BATCH_URL, UNSUBSCRIBE_PLACEHOLDER

    route = respx.post(RESEND_BATCH_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "e1"}]})
    )
    unsubscribe = "https://news.test/unsubscribe?token=T"

    mailer().send_edition(
        "ana@example.com",
        "Boas-vindas! Edição",
        f'<a href="{UNSUBSCRIBE_PLACEHOLDER}">sair</a>',
        f"sair: {UNSUBSCRIBE_PLACEHOLDER}",
        unsubscribe,
    )

    [email] = json.loads(route.calls.last.request.content)
    assert email["to"] == ["ana@example.com"]
    assert email["subject"] == "Boas-vindas! Edição"
    assert f'href="{unsubscribe}"' in email["html"]
    assert email["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@respx.mock
def test_edition_send_failure_raises_mail_error() -> None:
    from flanews.send.resend_sender import RESEND_BATCH_URL

    respx.post(RESEND_BATCH_URL).mock(return_value=httpx.Response(422, json={"message": "bad"}))

    with pytest.raises(MailError, match="bad"):
        mailer().send_edition("ana@example.com", "S", "h", "t", "https://n.test/u")
