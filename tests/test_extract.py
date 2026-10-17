from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flanews.models import Article
from flanews.processing.extract import (
    MAX_CONTENT_CHARS,
    DomainRateLimiter,
    extract_articles,
    extract_content,
)

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("America/Sao_Paulo")
ARTICLE_URL = (
    "https://www.uol.com.br/esporte/futebol/ultimas-noticias/2026/10/14/"
    "boto-flamengo-vasco-maracana.ghtm"
)


def make_article(url: str = ARTICLE_URL) -> Article:
    return Article(
        url=url,
        title="Boto fala sobre Vasco no Maracanã",
        source="google_news:UOL",
        published_at=datetime(2026, 10, 14, 12, 0, tzinfo=TZ),
        summary_hint="hint do RSS",
    )


def no_wait_limiter() -> DomainRateLimiter:
    return DomainRateLimiter(min_interval=0)


@respx.mock
def test_extract_content_fills_text_and_published_at() -> None:
    respx.get(ARTICLE_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "article_uol.html").read_text(encoding="utf-8")
        )
    )
    with httpx.Client() as client:
        result = extract_content(make_article(), client, no_wait_limiter())

    assert result.content is not None
    assert "José Boto" in result.content
    assert len(result.content) <= MAX_CONTENT_CHARS
    assert result.published_at == datetime(2026, 10, 14, 13, 31, 39, tzinfo=UTC)
    assert result.summary_hint == "hint do RSS"
    assert (
        result.image_url
        == "https://conteudo.imguol.com.br/c/esporte/2f/2026/03/23/jose-boto-diretor-de-futebol-do-flamengo-antes-de-partida-contra-o-corinthians-pelo-campeonato-brasileiro-1774235306838_v2_615x300.jpg"
    )


@respx.mock
def test_extract_content_ignores_non_https_image() -> None:
    html = (
        '<html><head><meta property="og:image" content="http://insecure.com/pic.jpg">'
        "</head><body><article><p>O Flamengo treinou forte.</p></article></body></html>"
    )
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=html))
    with httpx.Client() as client:
        result = extract_content(make_article(), client, no_wait_limiter())
    assert result.image_url is None


@pytest.mark.parametrize(
    "image",
    [
        "https://scontent.cdninstagram.com/v/t51/1_n.jpg?stp=x",
        "https://scontent-gru2-1.xx.fbcdn.net/v/t39/2_n.jpg",
    ],
)
@respx.mock
def test_extract_content_ignores_images_that_block_hotlinking(image) -> None:
    html = (
        f'<html><head><meta property="og:image" content="{image}">'
        "</head><body><article><p>O Flamengo treinou forte.</p></article></body></html>"
    )
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=html))
    with httpx.Client() as client:
        result = extract_content(make_article(), client, no_wait_limiter())
    assert result.image_url is None


@respx.mock
def test_extract_content_decodes_html_entities_in_the_image_url() -> None:
    html = (
        '<html><head><meta property="og:image" '
        'content="https://www.estadao.com.br/resizer/v2/X.jpg?quality=80&amp;auth=abc&amp;width=1200">'
        "</head><body><article><p>O Flamengo treinou forte.</p></article></body></html>"
    )
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=html))
    with httpx.Client() as client:
        result = extract_content(make_article(), client, no_wait_limiter())
    assert (
        result.image_url
        == "https://www.estadao.com.br/resizer/v2/X.jpg?quality=80&auth=abc&width=1200"
    )


@respx.mock
def test_extract_content_truncates_long_text() -> None:
    paragraphs = "".join(
        f"<p>Parágrafo {i}: "
        + "O Flamengo treinou forte nesta manhã no Ninho do Urubu. " * 20
        + "</p>"
        for i in range(40)  # ~46k chars, above MAX_CONTENT_CHARS
    )
    html = f"<html><body><article><h1>Título</h1>{paragraphs}</article></body></html>"
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=html))
    with httpx.Client() as client:
        result = extract_content(make_article(), client, no_wait_limiter())

    assert result.content is not None
    assert len(result.content) == MAX_CONTENT_CHARS


@respx.mock
def test_extract_content_failure_keeps_article(caplog) -> None:
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(404))
    article = make_article()
    with httpx.Client() as client:
        result = extract_content(article, client, no_wait_limiter())

    assert result.content is None
    assert result.summary_hint == "hint do RSS"
    assert result.published_at == article.published_at
    assert "Failed to extract" in caplog.text


@respx.mock
def test_extract_content_resolves_google_news_url() -> None:
    gn_url = "https://news.google.com/rss/articles/CBMabc?oc=5"
    respx.get(gn_url).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "google_news_article.html").read_text(encoding="utf-8")
        )
    )
    respx.post(url__startswith="https://news.google.com/_/").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "google_news_batchexecute.txt").read_text(encoding="utf-8")
        )
    )
    respx.get(ARTICLE_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "article_uol.html").read_text(encoding="utf-8")
        )
    )
    with httpx.Client() as client:
        result = extract_content(make_article(gn_url), client, no_wait_limiter())

    assert result.url == ARTICLE_URL
    assert result.content


@respx.mock
def test_extract_articles_processes_all_in_parallel_preserving_order() -> None:
    urls = [f"https://site{i}.com/noticia" for i in range(6)]
    for i, url in enumerate(urls):
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                text=f"<html><body><article><p>{'Notícia do Flamengo número ' * 10}{i}"
                "</p></article></body></html>",
            )
        )
    with httpx.Client() as client:
        results = extract_articles([make_article(url) for url in urls], client, no_wait_limiter())

    assert [r.url for r in results] == urls
    assert all(r.content for r in results)


def test_rate_limiter_waits_between_requests_to_same_domain() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = DomainRateLimiter(min_interval=1.0, clock=lambda: now[0], sleep=fake_sleep)
    limiter.wait("https://ge.globo.com/a")
    limiter.wait("https://www.flamengo.com.br/b")
    limiter.wait("https://ge.globo.com/c")

    assert sleeps == [1.0]
