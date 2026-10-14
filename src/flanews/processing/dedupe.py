import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from flanews.models import Article

logger = logging.getLogger(__name__)

TRACKING_PARAMS = {"fbclid", "gclid"}
TITLE_SIMILARITY_THRESHOLD = 85
SOURCE_PRIORITY = {"flamengo_oficial": 0, "ge": 1, "google_news": 2}

GOOGLE_NEWS_HOST = "news.google.com"
GOOGLE_NEWS_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
# Static request context expected by the "Fbv4je" (garturlreq) RPC.
GOOGLE_NEWS_REQUEST_CONTEXT = [
    ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
    "X",
    "X",
    1,
    [1, 1, 1],
    1,
    1,
    None,
    0,
    0,
    None,
    0,
]

RELEVANCE_PATTERN = re.compile(r"\bflamengo\b|\bfla\b|\bmengão\b|\brubro-negr[oa]s?\b", re.I)


def normalize_url(url: str) -> str:
    """Strip tracking query params (utm_*, fbclid, gclid) and the fragment."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def resolve_google_news_url(url: str, client: httpx.Client) -> str:
    """Decode a Google News article link into the publisher URL.

    Google News links no longer redirect over HTTP: the article page carries a
    signature (data-n-a-id/ts/sg) that must be posted to the batchexecute endpoint.
    Returns the original URL when it is not a Google News link or decoding fails.
    """
    if urlsplit(url).netloc != GOOGLE_NEWS_HOST:
        return url
    try:
        page = client.get(url)
        page.raise_for_status()
        attrs = {
            name: re.search(rf'data-n-a-{name}="([^"]+)"', page.text) for name in ("id", "ts", "sg")
        }
        if not all(attrs.values()):
            raise ValueError("signature attributes not found")
        payload = [
            "garturlreq",
            GOOGLE_NEWS_REQUEST_CONTEXT,
            attrs["id"][1],
            int(attrs["ts"][1]),
            attrs["sg"][1],
        ]
        f_req = json.dumps([[["Fbv4je", json.dumps(payload), None, "generic"]]])
        response = client.post(GOOGLE_NEWS_BATCHEXECUTE_URL, data={"f.req": f_req})
        response.raise_for_status()
        body = response.text.split("\n\n", 1)[1]
        envelope = json.loads(body)
        decoded = json.loads(envelope[0][2])[1]
        if not isinstance(decoded, str) or not decoded.startswith("http"):
            raise ValueError(f"unexpected decoded value: {decoded!r}")
        return decoded
    except Exception as e:
        logger.warning("Failed to resolve Google News URL %s: %s", url, e)
        return url


def source_priority(source: str) -> int:
    """Lower is better: flamengo_oficial > ge > google_news:* > others."""
    return SOURCE_PRIORITY.get(source.split(":", 1)[0], len(SOURCE_PRIORITY))


def dedupe(articles: list[Article]) -> list[Article]:
    """Drop duplicates by normalized URL, then by similar title.

    Among duplicates the article from the highest-priority source wins; the
    survivors keep their original relative order.
    """
    ranked = sorted(enumerate(articles), key=lambda item: source_priority(item[1].source))
    kept: list[tuple[int, Article]] = []
    seen_urls: set[str] = set()
    for index, article in ranked:
        url = normalize_url(article.url)
        if url in seen_urls:
            continue
        if any(
            fuzz.token_set_ratio(article.title, other.title, processor=default_process)
            >= TITLE_SIMILARITY_THRESHOLD
            for _, other in kept
        ):
            continue
        seen_urls.add(url)
        kept.append((index, article.model_copy(update={"url": url})))
    return [article for _, article in sorted(kept, key=lambda item: item[0])]


def is_relevant(article: Article) -> bool:
    """Cheap keyword filter: title or content must mention Flamengo."""
    text = f"{article.title}\n{article.content or ''}"
    return RELEVANCE_PATTERN.search(text) is not None
