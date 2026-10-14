import logging
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from selectolax.lexbor import LexborHTMLParser

from flanews.collectors.base import create_http_client
from flanews.models import Article

logger = logging.getLogger(__name__)

GE_FLAMENGO_URL = "https://ge.globo.com/futebol/times/flamengo/"


class GECollector:
    """Collector that scrapes latest news headlines from ge.globo Flamengo section."""

    name: str = "ge"

    def __init__(
        self,
        url: str = GE_FLAMENGO_URL,
        client: httpx.Client | None = None,
        tz_name: str = "America/Sao_Paulo",
    ) -> None:
        self.url = url
        self._client = client
        self.tz = ZoneInfo(tz_name)

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return create_http_client()

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        """Scrape ge.globo Flamengo page and extract articles within time window."""
        client = self._get_client()
        try:
            response = client.get(self.url)
            response.raise_for_status()
            html = response.text
        except Exception as e:
            logger.error("Failed to fetch ge.globo Flamengo page: %s", e)
            return []

        return self.parse_html(html, start, end)

    def parse_html(self, html: str, start: datetime, end: datetime) -> list[Article]:
        """Parse HTML string and extract Article models within [start, end]."""
        tree = LexborHTMLParser(html)
        articles: list[Article] = []
        seen_urls: set[str] = set()

        target_tz = self.tz
        start_tz = start.astimezone(target_tz) if start.tzinfo else start.replace(tzinfo=target_tz)
        end_tz = end.astimezone(target_tz) if end.tzinfo else end.replace(tzinfo=target_tz)

        # 1. First parse feed-post blocks if present (richer card metadata)
        post_nodes = tree.css(".feed-post")
        for post in post_nodes:
            link_node = post.css_first("a.feed-post-link")
            if not link_node:
                continue

            href = link_node.attributes.get("href", "")
            if not href or href in seen_urls:
                continue

            url = self._normalize_url(href)
            title = link_node.text(strip=True)
            if not title or len(title) < 8:
                continue

            time_node = post.css_first("span.feed-post-datetime")
            time_text = time_node.text(strip=True) if time_node else None

            published_at = self._extract_date_from_url(url, target_tz)
            if not (start_tz.date() <= published_at.date() <= end_tz.date()):
                continue

            seen_urls.add(href)
            seen_urls.add(url)
            articles.append(
                Article(
                    url=url,
                    title=title,
                    source="ge",
                    published_at=published_at,
                    summary_hint=time_text,
                )
            )

        # 2. Also inspect general headline links containing news and flamengo
        for a in tree.css("a"):
            href = a.attributes.get("href", "")
            if not href:
                continue

            if not ("/noticia/" in href and ("/flamengo/" in href or "flamengo" in href.lower())):
                continue

            url = self._normalize_url(href)
            if url in seen_urls or href in seen_urls:
                continue

            title = a.text(strip=True)
            if not title or len(title) < 10:
                continue

            published_at = self._extract_date_from_url(url, target_tz)
            if not (start_tz.date() <= published_at.date() <= end_tz.date()):
                continue

            seen_urls.add(href)
            seen_urls.add(url)
            articles.append(
                Article(
                    url=url,
                    title=title,
                    source="ge",
                    published_at=published_at,
                )
            )

        return articles

    def _normalize_url(self, href: str) -> str:
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return "https://ge.globo.com" + href
        return href

    def _extract_date_from_url(self, url: str, tz: ZoneInfo) -> datetime:
        # Match /noticia/YYYY/MM/DD/
        match = re.search(r"/noticia/(\d{4})/(\d{2})/(\d{2})/", url)
        if match:
            year, month, day = map(int, match.groups())
            return datetime.combine(datetime(year, month, day).date(), time(12, 0, 0), tzinfo=tz)
        return datetime.now(tz)
