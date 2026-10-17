import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import trafilatura
from dateutil.parser import isoparse

from flanews.models import Article
from flanews.processing.dedupe import (
    GOOGLE_NEWS_HOST,
    normalize_url,
    resolve_google_news_url,
)

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 4000
MAX_WORKERS = 5
DEFAULT_MIN_INTERVAL = 1.0
TZ = ZoneInfo("America/Sao_Paulo")

PUBLISHED_PATTERNS = (
    re.compile(r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"', re.I),
    re.compile(r'<meta[^>]+content="([^"]+)"[^>]+property="article:published_time"', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
)

IMAGE_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
)


# Hosts whose image links answer 403 outside their own site (signed, anti-hotlinking).
BLOCKED_IMAGE_HOSTS = ("cdninstagram.com", "fbcdn.net")


def _extract_og_image(html: str) -> str | None:
    for pattern in IMAGE_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        url = match.group(1).strip()
        host = urlsplit(url).hostname or ""
        if url.startswith("https://") and not host.endswith(BLOCKED_IMAGE_HOSTS):
            return url
    return None


class DomainRateLimiter:
    """Thread-safe limiter enforcing a minimum interval between requests per domain."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        domain = urlsplit(url).netloc
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_allowed.get(domain, now))
            self._next_allowed[domain] = slot + self.min_interval
        delay = slot - now
        if delay > 0:
            self._sleep(delay)


class _RateLimitedClient:
    """Wraps an httpx client so every request waits on the domain rate limiter."""

    def __init__(self, client: httpx.Client, limiter: DomainRateLimiter) -> None:
        self._client = client
        self._limiter = limiter

    def get(self, url: str, **kwargs) -> httpx.Response:
        self._limiter.wait(url)
        return self._client.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        self._limiter.wait(url)
        return self._client.post(url, **kwargs)


def _extract_published_at(html: str) -> datetime | None:
    for pattern in PUBLISHED_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        try:
            parsed = isoparse(match.group(1))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return parsed.astimezone(TZ)
    return None


def extract_content(article: Article, client: httpx.Client, limiter: DomainRateLimiter) -> Article:
    """Resolve the final URL, download the page and extract its main text.

    `published_at` is replaced by the page's own timestamp when it has a timezone
    (collectors may only know the date). On failure the article is returned with
    its `summary_hint` untouched and a warning is logged.
    """
    limited = _RateLimitedClient(client, limiter)
    url = article.url
    if urlsplit(url).netloc == GOOGLE_NEWS_HOST:
        url = resolve_google_news_url(url, limited)  # type: ignore[arg-type]
    url = normalize_url(url)
    article = article.model_copy(update={"url": url})

    try:
        response = limited.get(url)
        response.raise_for_status()
        html = response.text
        text = trafilatura.extract(html, url=url)
        if not text:
            raise ValueError("no extractable text")
    except Exception as e:
        logger.warning("Failed to extract content from %s: %s", url, e)
        return article

    update: dict[str, object] = {"content": text[:MAX_CONTENT_CHARS]}
    published_at = _extract_published_at(html)
    if published_at is not None:
        update["published_at"] = published_at
    image_url = _extract_og_image(html)
    if image_url is not None:
        update["image_url"] = image_url
    return article.model_copy(update=update)


def extract_articles(
    articles: list[Article],
    client: httpx.Client,
    limiter: DomainRateLimiter | None = None,
    max_workers: int = MAX_WORKERS,
) -> list[Article]:
    """Run `extract_content` in parallel, preserving input order."""
    limiter = limiter or DomainRateLimiter()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(lambda a: extract_content(a, client, limiter), articles))
