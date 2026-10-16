import json

import httpx
import pytest
import respx
from tenacity import wait_none

from flanews.config import Settings
from flanews.send.recipients import (
    Recipient,
    latest_edition_subject,
    publish_latest_edition,
    resolve_recipients,
)

API = "https://news.test/api/subscribers"
MAILTO = "mailto:news@fla.com?subject=Descadastrar"


def settings(token: str | None = "api-token", recipients: str = "dono@x.com") -> Settings:
    return Settings(
        NEWSLETTER_FROM="Flamengo News <news@fla.com>",
        NEWSLETTER_RECIPIENTS=recipients,
        PUBLIC_URL="https://news.test/",
        SUBSCRIBERS_API_TOKEN=token,
    )


def resolve(s: Settings):
    return resolve_recipients(s, client=httpx.Client(), wait=wait_none())


@respx.mock
def test_without_api_token_uses_only_the_fixed_list() -> None:
    route = respx.get(API)

    result = resolve(settings(token=None, recipients="dono@x.com, outro@x.com"))

    assert result.recipients == [
        Recipient("dono@x.com", MAILTO),
        Recipient("outro@x.com", MAILTO),
    ]
    assert result.from_api == 0
    assert not route.called


@respx.mock
def test_merges_fixed_list_with_subscribers_without_repeating() -> None:
    route = respx.get(API).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"email": "Dono@X.com", "unsubscribe_url": "https://news.test/unsubscribe?t=1"},
                {"email": "ana@y.com", "unsubscribe_url": "https://news.test/unsubscribe?t=2"},
            ],
        )
    )

    result = resolve(settings())

    assert route.calls.last.request.headers["Authorization"] == "Bearer api-token"
    assert result.recipients == [
        Recipient("dono@x.com", "https://news.test/unsubscribe?t=1"),
        Recipient("ana@y.com", "https://news.test/unsubscribe?t=2"),
    ]
    assert result.from_api == 2


@respx.mock
def test_api_failure_falls_back_to_the_fixed_list(caplog) -> None:
    route = respx.get(API).mock(return_value=httpx.Response(503))

    with caplog.at_level("ERROR"):
        result = resolve(settings())

    assert result.recipients == [Recipient("dono@x.com", MAILTO)]
    assert result.from_api == 0
    assert route.call_count == 3
    assert "subscribers" in caplog.text.lower()


@respx.mock
def test_unauthorized_or_malformed_response_falls_back(caplog) -> None:
    respx.get(API).mock(return_value=httpx.Response(401))
    assert resolve(settings()).from_api == 0

    respx.get(API).mock(return_value=httpx.Response(200, json={"oops": True}))
    assert resolve(settings()).recipients == [Recipient("dono@x.com", MAILTO)]


@respx.mock
def test_network_error_falls_back() -> None:
    respx.get(API).mock(side_effect=httpx.ConnectError("down"))

    assert resolve(settings()).recipients == [Recipient("dono@x.com", MAILTO)]


@respx.mock
def test_publish_latest_edition_puts_it_with_the_token() -> None:
    route = respx.put("https://news.test/api/latest-edition").mock(return_value=httpx.Response(204))

    publish_latest_edition(settings(), "Assunto", "<p>h</p>", "t", client=httpx.Client())

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer api-token"
    assert json.loads(request.content) == {"subject": "Assunto", "html": "<p>h</p>", "text": "t"}


@respx.mock
def test_publish_latest_edition_raises_on_error() -> None:
    respx.put("https://news.test/api/latest-edition").mock(return_value=httpx.Response(401))

    with pytest.raises(httpx.HTTPStatusError):
        publish_latest_edition(settings(), "A", "h", "t", client=httpx.Client())


@respx.mock
def test_latest_edition_subject_reads_it_with_the_token() -> None:
    route = respx.get("https://news.test/api/latest-edition").mock(
        return_value=httpx.Response(200, json={"subject": "Urubu News — Edição de Sexta"})
    )

    subject = latest_edition_subject(settings(), client=httpx.Client())

    assert subject == "Urubu News — Edição de Sexta"
    assert route.calls.last.request.headers["Authorization"] == "Bearer api-token"


@respx.mock
def test_latest_edition_subject_is_none_when_nothing_was_published() -> None:
    respx.get("https://news.test/api/latest-edition").mock(return_value=httpx.Response(404))

    assert latest_edition_subject(settings(), client=httpx.Client()) is None


@respx.mock
def test_latest_edition_subject_raises_on_error() -> None:
    respx.get("https://news.test/api/latest-edition").mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        latest_edition_subject(settings(), client=httpx.Client())
