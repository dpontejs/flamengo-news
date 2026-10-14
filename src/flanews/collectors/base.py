from datetime import datetime
from typing import Protocol

import httpx

from flanews.config import Settings, get_settings
from flanews.models import Article

USER_AGENT = "flanews/0.1 (+contato@flanews.local)"
DEFAULT_TIMEOUT = 15.0


def create_http_client() -> httpx.Client:
    """Create a configured HTTP client for collectors."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )


class Collector(Protocol):
    """Protocol defining news collector interface."""

    name: str

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        """Collect articles within the given time window."""
        ...


def get_collectors(settings: Settings | None = None) -> list[Collector]:
    """Return all registered collectors."""
    if settings is None:
        settings = get_settings()

    from flanews.collectors.google_news import GoogleNewsCollector

    return [
        GoogleNewsCollector(),
    ]
