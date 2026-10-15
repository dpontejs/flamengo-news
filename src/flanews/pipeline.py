import logging

import httpx

from flanews.collectors.base import Collector, create_http_client, get_collectors
from flanews.config import Settings
from flanews.models import Article, Edition
from flanews.processing.dedupe import dedupe, is_relevant
from flanews.processing.extract import DomainRateLimiter, extract_articles

logger = logging.getLogger(__name__)


def collect_articles(
    edition: Edition,
    settings: Settings | None = None,
    collectors: list[Collector] | None = None,
    client: httpx.Client | None = None,
    limiter: DomainRateLimiter | None = None,
) -> list[Article]:
    """Collect, dedupe, extract and filter the articles of an edition, newest first.

    A failing collector is logged and skipped. Dedupe runs again after extraction
    because Google News links only become publisher URLs at that point, and the
    window is re-checked because extraction may refine `published_at`.
    """
    if collectors is None:
        collectors = get_collectors(settings)

    collected: list[Article] = []
    for collector in collectors:
        try:
            articles = collector.collect(edition.start, edition.end)
        except Exception:
            logger.exception("Collector %s failed", collector.name)
            continue
        logger.info("Collector %s returned %d articles", collector.name, len(articles))
        collected.extend(articles)

    unique = dedupe(collected)
    if client is None:
        with create_http_client() as own_client:
            extracted = extract_articles(unique, own_client, limiter)
    else:
        extracted = extract_articles(unique, client, limiter)

    result = [
        article
        for article in dedupe(extracted)
        if edition.start <= article.published_at <= edition.end and is_relevant(article)
    ]
    logger.info("Collected %d articles (%d before filtering)", len(result), len(collected))
    return sorted(result, key=lambda a: a.published_at, reverse=True)
