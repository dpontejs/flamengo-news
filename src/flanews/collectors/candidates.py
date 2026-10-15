"""Headline-only candidates for the "Saiba mais" and "Brasil afora" sections.

Candidates are not text-extracted up front: the LLM picks a few of them in the
grouping call and only those are downloaded.
"""

import logging
import re
from datetime import UTC, datetime
from html import unescape

import feedparser
import httpx

from flanews.collectors.base import create_http_client
from flanews.collectors.google_news import GoogleNewsCollector, google_news_url
from flanews.models import Article

logger = logging.getLogger(__name__)

# Other Flamengo sports the newsletter may mention (name -> Google News query).
# The LLM only picks what is relevant, so a sport can be absent from an edition.
EXTRAS = {
    "Basquete": '"Flamengo" basquete OR NBB',
    "Vôlei": '"Sesc-Flamengo" OR "Flamengo" vôlei',
    "Futebol feminino": '"Flamengo" futebol feminino',
}
EXTRA_LIMIT = 15
# Social posts come with the whole caption as title and duplicate real news.
SOCIAL_SOURCES = {"instagram", "facebook", "tiktok", "youtube", "x"}

GE_FOOTBALL_RSS_URL = "https://ge.globo.com/rss/ge/futebol/"
GE_SERIE_A_RSS_URL = "https://ge.globo.com/rss/ge/futebol/brasileirao-serie-a/"
# The general feed spans only ~1 day; the Série A feed covers whole edition windows.
GE_FEEDS = (GE_FOOTBALL_RSS_URL, GE_SERIE_A_RSS_URL)
BRAZIL_GOOGLE_NEWS_QUERY = 'Brasileirão OR "Copa do Brasil" OR "Série B" -Flamengo'
BRAZIL_LIMIT = 40
FLAMENGO_PATTERN = re.compile(r"flamengo|mengão|rubro-negr", re.I)
TAG_PATTERN = re.compile(r"<[^>]+>")


def _clean(html: str | None) -> str | None:
    """Plain-text hint: feeds ship summaries as HTML snippets."""
    return " ".join(unescape(TAG_PATTERN.sub(" ", html or "")).split()) or None


class ExtrasCollector:
    """One Google News search per extra sport, tagged with section/category."""

    name = "extras"

    def __init__(
        self, extras: dict[str, str] | None = None, client: httpx.Client | None = None
    ) -> None:
        self.extras = EXTRAS if extras is None else extras
        self._client = client

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        articles: list[Article] = []
        for category, query in self.extras.items():
            found = GoogleNewsCollector(
                rss_url=google_news_url(query), client=self._client
            ).collect(start, end)
            found = [a for a in found if a.source.split(":", 1)[-1].lower() not in SOCIAL_SOURCES]
            found.sort(key=lambda a: a.published_at, reverse=True)
            articles.extend(
                a.model_copy(
                    update={
                        "section": "saiba_mais",
                        "category": category,
                        "summary_hint": _clean(a.summary_hint),
                    }
                )
                for a in found[:EXTRA_LIMIT]
            )
        return articles


class BrazilCollector:
    """Brazilian football from ge's RSS feeds plus a Google News search.

    News *about* Flamengo (title mentions it) is left out, since the rest of the
    newsletter covers it; news that only mention Flamengo in passing stay.
    """

    name = "brasil"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        client = self._client or create_http_client()
        articles: dict[str, Article] = {}
        for url in GE_FEEDS:
            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception as e:
                logger.warning("Failed to fetch ge RSS %s: %s", url, e)
                continue
            for article in self._parse(response.text, start, end):
                articles.setdefault(article.url, article)
        searched = GoogleNewsCollector(
            rss_url=google_news_url(BRAZIL_GOOGLE_NEWS_QUERY), client=self._client
        ).collect(start, end)
        for article in searched:
            if not FLAMENGO_PATTERN.search(article.title):
                articles.setdefault(
                    article.url,
                    article.model_copy(
                        update={"section": "brasil", "summary_hint": _clean(article.summary_hint)}
                    ),
                )
        ordered = sorted(articles.values(), key=lambda a: a.published_at, reverse=True)
        return ordered[:BRAZIL_LIMIT]

    def _parse(self, feed: str, start: datetime, end: datetime) -> list[Article]:
        articles: list[Article] = []
        for entry in feedparser.parse(feed).entries:
            if not entry.get("published_parsed") or not entry.get("link"):
                continue
            published = datetime(*entry.published_parsed[:6], tzinfo=UTC).astimezone(start.tzinfo)
            hint = _clean(entry.get("summary"))
            if not (start <= published <= end):
                continue
            if FLAMENGO_PATTERN.search(entry.title):
                continue
            articles.append(
                Article(
                    url=entry.link,
                    title=entry.title,
                    source="ge",
                    published_at=published,
                    summary_hint=hint,
                    section="brasil",
                )
            )
        return articles
