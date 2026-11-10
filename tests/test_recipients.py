import json

import httpx
import pytest
import respx
from tenacity import wait_none

from flanews.config import Settings
from flanews.send.recipients import (
    Recipient,
    latest_edition,
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
def test_latest_edition_reads_subject_and_send_time_with_the_token() -> None:
    body = {"subject": "Urubu News — Notícias", "published_at": "2026-10-16T19:11:00-03:00"}
    route = respx.get("https://news.test/api/latest-edition").mock(
        return_value=httpx.Response(200, json=body)
    )

    edition = latest_edition(settings(), client=httpx.Client())

    assert edition.subject == "Urubu News — Notícias"
    assert edition.published_at.isoformat() == "2026-10-16T19:11:00-03:00"
    assert route.calls.last.request.headers["Authorization"] == "Bearer api-token"


@respx.mock
def test_latest_edition_subject_is_none_when_nothing_was_published() -> None:
    respx.get("https://news.test/api/latest-edition").mock(return_value=httpx.Response(404))

    assert latest_edition(settings(), client=httpx.Client()) is None


@respx.mock
def test_latest_edition_subject_raises_on_error() -> None:
    respx.get("https://news.test/api/latest-edition").mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        latest_edition(settings(), client=httpx.Client())


def test_latest_edition_topic_titles_come_from_the_news_section() -> None:
    from flanews.send.recipients import LatestEdition

    text = (
        "URUBU NEWS\n\n== Notícias ==\n\n* Empate em La Plata\nResumo.\n  - ge: https://x\n\n"
        "* Jorginho volta\nResumo.\n\n== Saiba mais ==\n\n* [Basquete] Título\n"
    )
    edition = LatestEdition(subject="s", published_at="2026-10-16T19:11:00-03:00", text=text)

    assert edition.topic_titles == ["Empate em La Plata", "Jorginho volta"]
    assert LatestEdition(subject="s", published_at="2026-10-16T19:11:00-03:00").topic_titles == []


SUMMARY = {
    "fla_goals": 2,
    "opp_goals": 1,
    "exact": ["Ana"],
    "top": [{"nickname": "Ana", "points": 5, "exact": 1}],
    "king": "Ana",
    "cold_foot": None,
}


@respx.mock
def test_subscribers_bet_token_reaches_the_recipient() -> None:
    respx.get(API).mock(
        return_value=httpx.Response(
            200,
            json=[{"email": "ana@x.com", "unsubscribe_url": "https://u/1", "bet_token": "B1"}],
        )
    )

    result = resolve(settings(recipients="dono@x.com"))

    assert Recipient("ana@x.com", "https://u/1", "B1") in result.recipients
    assert Recipient("dono@x.com", MAILTO) in result.recipients


@respx.mock
def test_register_match_puts_the_fixture() -> None:
    from datetime import UTC, datetime

    from flanews.send.recipients import register_match

    route = respx.put("https://news.test/api/bolao/matches/401").mock(
        return_value=httpx.Response(204)
    )

    register_match(settings(), "401", "Bahia", False, datetime(2026, 11, 15, 21, tzinfo=UTC))

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer api-token"
    assert json.loads(request.content) == {
        "opponent": "Bahia",
        "flamengo_home": False,
        "kickoff": "2026-11-15T21:00:00+00:00",
    }


@respx.mock
def test_report_result_returns_the_summary() -> None:
    from flanews.send.recipients import report_result

    route = respx.put("https://news.test/api/bolao/matches/401/result").mock(
        return_value=httpx.Response(200, json=SUMMARY)
    )

    summary = report_result(settings(), "401", 2, 1)

    assert json.loads(route.calls.last.request.content) == {"fla_goals": 2, "opp_goals": 1}
    assert summary.exact == ["Ana"] and summary.king == "Ana"


@respx.mock
def test_preview_summary_only_reads() -> None:
    from flanews.send.recipients import preview_summary

    route = respx.get("https://news.test/api/bolao/matches/401/summary").mock(
        return_value=httpx.Response(200, json=SUMMARY)
    )

    summary = preview_summary(settings(), "401", 2, 1)

    assert dict(route.calls.last.request.url.params) == {"fla": "2", "opp": "1"}
    assert summary.top[0].points == 5


@respx.mock
def test_unknown_match_result_raises() -> None:
    from flanews.send.recipients import report_result

    respx.put("https://news.test/api/bolao/matches/401/result").mock(
        return_value=httpx.Response(404, json={"detail": "unknown match"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        report_result(settings(), "401", 2, 1)
