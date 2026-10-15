import logging
from datetime import UTC, datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import httpx

from flanews.collectors.base import create_http_client
from flanews.models import Article

logger = logging.getLogger(__name__)


def google_news_url(query: str) -> str:
    """Google News RSS search URL for `query` in Brazilian Portuguese."""
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


GOOGLE_NEWS_RSS_URL = google_news_url("Flamengo futebol")


class GoogleNewsCollector:
    """Collector that fetches articles from Google News RSS feed."""

    name: str = "google_news"

    def __init__(
        self,
        rss_url: str = GOOGLE_NEWS_RSS_URL,
        client: httpx.Client | None = None,
        tz_name: str = "America/Sao_Paulo",
    ) -> None:
        self.rss_url = rss_url
        self._client = client
        self.tz = ZoneInfo(tz_name)

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return create_http_client()

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        """Fetch and filter RSS articles within the [start, end] window."""
        client = self._get_client()
        try:
            response = client.get(self.rss_url)
            response.raise_for_status()
            content = response.text
        except Exception as e:
            logger.error("Failed to fetch Google News RSS feed: %s", e)
            return []

        feed = feedparser.parse(content)
        articles: list[Article] = []

        # Ensure start and end have matching timezone
        target_tz = self.tz
        start_tz = start.astimezone(target_tz) if start.tzinfo else start.replace(tzinfo=target_tz)
        end_tz = end.astimezone(target_tz) if end.tzinfo else end.replace(tzinfo=target_tz)

        for entry in feed.entries:
            published_at = self._extract_date(entry, target_tz)
            if published_at is None:
                continue

            if not (start_tz <= published_at <= end_tz):
                continue

            source_title = None
            if isinstance(entry.get("source"), dict):
                source_title = entry["source"].get("title")

            source = f"google_news:{source_title}" if source_title else "google_news"
            url = getattr(entry, "link", None)
            title = getattr(entry, "title", None)

            if not url or not title:
                continue

            summary_hint = entry.get("summary") or entry.get("description")

            articles.append(
                Article(
                    url=url,
                    title=title,
                    source=source,
                    published_at=published_at,
                    summary_hint=summary_hint,
                )
            )

        return articles

    def _extract_date(self, entry: feedparser.FeedParserDict, tz: ZoneInfo) -> datetime | None:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            dt_utc = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            return dt_utc.astimezone(tz)
        return None
