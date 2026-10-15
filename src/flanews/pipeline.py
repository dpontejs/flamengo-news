import logging
from collections.abc import Callable
from email.utils import parseaddr
from typing import Protocol

import httpx

from flanews.collectors.base import Collector, create_http_client, get_collectors
from flanews.config import Settings, get_settings
from flanews.models import (
    Article,
    Edition,
    MatchStats,
    Newsletter,
    NextMatch,
    StandingRow,
    TeamMoment,
)
from flanews.processing.dedupe import dedupe, is_relevant
from flanews.processing.extract import DomainRateLimiter, extract_articles
from flanews.stats.espn import ESPNStatsClient
from flanews.summarizer.client import LLMClient, LLMError, get_llm_client
from flanews.summarizer.pipeline import EditionSummary, summarize_edition, write_analysis

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


class StatsClient(Protocol):
    def get_last_match(self, start, end) -> MatchStats | None: ...
    def get_next_match(self, now) -> NextMatch | None: ...
    def get_standings(self, league: str = "bra.1") -> list[StandingRow]: ...
    def get_moment(self, end, standings: list[StandingRow]) -> TeamMoment | None: ...


def build_newsletter(
    edition: Edition,
    settings: Settings | None = None,
    collect: Callable[[Edition, Settings], list[Article]] | None = None,
    stats_client: StatsClient | None = None,
    llm: LLMClient | None = None,
) -> Newsletter:
    """Collect news and stats for the edition and summarize them into a Newsletter.

    Stats failures already degrade to None/[]; an LLM failure is logged and the
    newsletter keeps the stats sections without news topics.
    """
    settings = settings or get_settings()
    collect = collect or collect_articles
    stats_client = stats_client or ESPNStatsClient(
        team_id=settings.FLAMENGO_TEAM_ID, tz_name=settings.TIMEZONE
    )

    articles = collect(edition, settings)
    last_match = stats_client.get_last_match(edition.start, edition.end)
    next_match = stats_client.get_next_match(edition.end)
    standings = stats_client.get_standings("bra.1")
    moment = stats_client.get_moment(edition.end, standings)

    try:
        llm = llm or get_llm_client(settings)
        summary = summarize_edition(articles, llm, last_match=last_match, label=edition.label)
    except LLMError as e:
        logger.error("Summarization failed, sending stats only: %s", e)
        summary = EditionSummary()

    analysis = ""
    if last_match is not None and llm is not None:
        try:
            analysis = write_analysis(last_match, moment, llm)
        except LLMError as e:
            logger.error("Match analysis failed, keeping the numbers only: %s", e)

    return Newsletter(
        edition=edition,
        headline=summary.headline,
        intro=summary.intro,
        analysis=analysis,
        moment=moment,
        topics=summary.topics,
        last_match=last_match,
        next_match=next_match,
        standings=standings,
    )


def unsubscribe_url(settings: Settings) -> str:
    """mailto: link to the sender address, used in the footer and List-Unsubscribe."""
    _, address = parseaddr(settings.NEWSLETTER_FROM)
    return f"mailto:{address}?subject=Descadastrar"
