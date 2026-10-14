from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import respx

from flanews.models import Article
from flanews.processing.dedupe import (
    GOOGLE_NEWS_BATCHEXECUTE_URL,
    dedupe,
    is_relevant,
    normalize_url,
    resolve_google_news_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("America/Sao_Paulo")
GN_URL = (
    "https://news.google.com/rss/articles/CBMiogFBVV95cUxOeldnRkR4U05kZkZFRE9WbEhMalNFZG9ySEVSY0RF"
    "UjFyU1pMeFh2a0dqUmM5eVIyRVFzTFJtTTJoOXBkRy1GQmplVlJQU0E0ZXR5U2hCQTZoblIyRmFucklvOEFrQnhJTmRu"
    "RzRxNjVrbUZ1RFBNdjBWZXBNeGgyaVBWbmliTXB5aWZuUGthUzVaTnExSFRzZkdyMWNpdl9KeVE?oc=5"
)
DECODED_URL = (
    "https://www.uol.com.br/esporte/futebol/ultimas-noticias/2026/10/14/"
    "boto-flamengo-vasco-maracana.ghtm"
)


def make_article(url: str, title: str, source: str = "ge") -> Article:
    return Article(
        url=url, title=title, source=source, published_at=datetime(2026, 10, 14, tzinfo=TZ)
    )


def test_normalize_url_removes_tracking_params_and_fragment() -> None:
    url = "https://ge.globo.com/a.ghtml?utm_source=x&utm_medium=y&id=3&fbclid=abc#comments"
    assert normalize_url(url) == "https://ge.globo.com/a.ghtml?id=3"


def test_normalize_url_without_query_is_unchanged() -> None:
    assert normalize_url("https://www.flamengo.com.br/noticias/x") == (
        "https://www.flamengo.com.br/noticias/x"
    )


@respx.mock
def test_resolve_google_news_url_decodes_publisher_url() -> None:
    respx.get(url__startswith="https://news.google.com/rss/articles/").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "google_news_article.html").read_text(encoding="utf-8")
        )
    )
    route = respx.post(GOOGLE_NEWS_BATCHEXECUTE_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "google_news_batchexecute.txt").read_text(encoding="utf-8")
        )
    )

    with httpx.Client() as client:
        assert resolve_google_news_url(GN_URL, client) == DECODED_URL
    assert b"Fbv4je" in route.calls.last.request.content


@respx.mock
def test_resolve_google_news_url_returns_original_on_failure() -> None:
    respx.get(url__startswith="https://news.google.com/rss/articles/").mock(
        return_value=httpx.Response(500)
    )
    with httpx.Client() as client:
        assert resolve_google_news_url(GN_URL, client) == GN_URL


def test_resolve_google_news_url_ignores_other_hosts() -> None:
    with httpx.Client() as client:
        url = "https://ge.globo.com/a.ghtml"
        assert resolve_google_news_url(url, client) == url


def test_dedupe_by_normalized_url_keeps_higher_priority_source() -> None:
    articles = [
        make_article("https://x.com/a?utm_source=gn", "Título A", "google_news:X"),
        make_article("https://x.com/a", "Título A diferente", "flamengo_oficial"),
    ]
    result = dedupe(articles)
    assert len(result) == 1
    assert result[0].source == "flamengo_oficial"
    assert result[0].url == "https://x.com/a"


def test_dedupe_by_similar_title_keeps_higher_priority_source() -> None:
    articles = [
        make_article(
            "https://lance.com.br/1",
            "Flamengo vence o Palmeiras no Maracanã e assume a liderança - Lance!",
            "google_news:Lance!",
        ),
        make_article(
            "https://ge.globo.com/2",
            "Flamengo vence o Palmeiras no Maracanã e assume a liderança",
            "ge",
        ),
        make_article(
            "https://flamengo.com.br/3", "Filipe Luís fala sobre a semana", "flamengo_oficial"
        ),
    ]
    result = dedupe(articles)
    assert [a.source for a in result] == ["ge", "flamengo_oficial"]


def test_dedupe_keeps_distinct_titles() -> None:
    articles = [
        make_article("https://ge.globo.com/1", "Flamengo vence o Palmeiras"),
        make_article("https://ge.globo.com/2", "Pedro sofre lesão muscular e desfalca o time"),
    ]
    assert len(dedupe(articles)) == 2


def test_is_relevant_matches_keywords_in_title_or_content() -> None:
    assert is_relevant(make_article("https://a/1", "Mengão vence clássico"))
    assert is_relevant(make_article("https://a/2", "Fla-Flu termina empatado"))
    assert is_relevant(make_article("https://a/3", "Torcida RUBRO-NEGRA lota estádio"))
    with_content = make_article("https://a/4", "Clássico no Maracanã")
    with_content.content = "O Flamengo venceu."
    assert is_relevant(with_content)


def test_is_relevant_rejects_unrelated_article() -> None:
    assert not is_relevant(make_article("https://a/5", "Flávio marca e Palmeiras vence"))
