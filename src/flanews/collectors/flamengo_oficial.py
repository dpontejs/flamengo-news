import logging
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from selectolax.lexbor import LexborHTMLParser

from flanews.collectors.base import create_http_client
from flanews.models import Article

logger = logging.getLogger(__name__)

FLAMENGO_OFICIAL_URL = "https://www.flamengo.com.br/noticias"


class FlamengoOficialCollector:
    """Collector that scrapes the official Clube de Regatas do Flamengo website."""

    name: str = "flamengo_oficial"

    def __init__(
        self,
        url: str = FLAMENGO_OFICIAL_URL,
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
        """Scrape official site and extract articles within time window."""
        client = self._get_client()
        try:
            response = client.get(self.url)
            response.raise_for_status()
            html = response.text
        except Exception as e:
            logger.error("Failed to fetch official Flamengo site: %s", e)
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

        # Ignore general category listing navigation links
        ignored_links = {
            "/noticias",
            "/noticias/",
            "/noticias/ultimas-noticias",
            "/noticias/futebol",
            "/noticias/ingressos",
            "/noticias/notas-oficiais",
        }

        for a in tree.css('a[href*="/noticias/"]'):
            href = a.attributes.get("href", "")
            if not href or href in ignored_links:
                continue

            url = self._normalize_url(href)
            if url in seen_urls:
                continue

            # Extract title
            h3 = a.css_first("h3, [class*='editorialTitle']")
            title = h3.text(strip=True) if h3 else a.text(strip=True)
            if not title or len(title) < 5:
                continue

            # Extract summary hint
            p = a.css_first("p, [class*='editorialSummary']")
            summary_hint = p.text(strip=True) if p else None

            # Extract published date
            published_at = self._extract_date(a, target_tz)
            if not (start_tz.date() <= published_at.date() <= end_tz.date()):
                continue

            seen_urls.add(url)
            articles.append(
                Article(
                    url=url,
                    title=title,
                    source="flamengo_oficial",
                    published_at=published_at,
                    summary_hint=summary_hint,
                )
            )

        return articles

    def _normalize_url(self, href: str) -> str:
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return "https://www.flamengo.com.br" + href
        return href

    def _extract_date(self, node: object, tz: ZoneInfo) -> datetime:
        date_node = getattr(node, "css_first", lambda _: None)("[class*='editorialPublished']")
        date_text = date_node.text(strip=True) if date_node else getattr(node, "text", lambda: "")()

        # Match DD/MM/YY or DD/MM/YYYY
        match = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", date_text)
        if match:
            day, month, year = map(int, match.groups())
            if year < 100:
                year += 2000
            return datetime.combine(datetime(year, month, day).date(), time(12, 0, 0), tzinfo=tz)
        return datetime.now(tz)
