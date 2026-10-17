"""Client of the subscription page API: who receives an edition, and the latest edition.

Recipients are the fixed list plus the page's active subscribers; after a real send the edition
is published back so new subscribers get it right after confirming.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from flanews.config import Settings

logger = logging.getLogger(__name__)

FETCH_ATTEMPTS = 3
TIMEOUT = 15.0


@dataclass(frozen=True)
class Recipient:
    email: str
    unsubscribe_url: str


@dataclass(frozen=True)
class ResolvedRecipients:
    recipients: list[Recipient]
    from_api: int


class _Subscriber(BaseModel):
    email: str
    unsubscribe_url: str


_subscribers = TypeAdapter(list[_Subscriber])


def mailto_unsubscribe(settings: Settings) -> str:
    """mailto: link to the sender address, for the fixed list (it has no signed link)."""
    _, address = parseaddr(settings.NEWSLETTER_FROM)
    return f"mailto:{address}?subject=Descadastrar"


def _retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


def fetch_subscribers(
    settings: Settings, client: httpx.Client, wait: wait_base
) -> list[_Subscriber]:
    url = settings.PUBLIC_URL.rstrip("/") + "/api/subscribers"

    def get() -> httpx.Response:
        response = client.get(
            url, headers={"Authorization": f"Bearer {settings.SUBSCRIBERS_API_TOKEN}"}
        )
        response.raise_for_status()
        return response

    retrying = Retrying(
        stop=stop_after_attempt(FETCH_ATTEMPTS),
        wait=wait,
        retry=retry_if_exception(_retryable),
        reraise=True,
    )
    return _subscribers.validate_python(retrying(get).json())


def resolve_recipients(
    settings: Settings,
    client: httpx.Client | None = None,
    wait: wait_base | None = None,
) -> ResolvedRecipients:
    """Fixed list + API subscribers, once each. If the API fails, only the fixed list."""
    mailto = mailto_unsubscribe(settings)
    merged: dict[str, Recipient] = {}
    for email in settings.NEWSLETTER_RECIPIENTS:
        merged.setdefault(email.strip().lower(), Recipient(email.strip().lower(), mailto))

    from_api = 0
    if settings.SUBSCRIBERS_API_TOKEN:
        try:
            subscribers = fetch_subscribers(
                settings,
                client or httpx.Client(timeout=TIMEOUT),
                wait or wait_exponential(multiplier=2, max=20),
            )
        except (httpx.HTTPError, ValidationError, ValueError) as e:
            logger.error("Could not fetch subscribers, sending to the fixed list only: %s", e)
        else:
            from_api = len(subscribers)
            for s in subscribers:
                email = s.email.strip().lower()
                # A subscriber's signed link beats the fixed list's mailto.
                merged[email] = Recipient(email, s.unsubscribe_url)
    return ResolvedRecipients(list(merged.values()), from_api)


def publish_latest_edition(
    settings: Settings,
    subject: str,
    html: str,
    text: str,
    client: httpx.Client | None = None,
) -> None:
    """PUT the edition (unsubscribe placeholder included) to the page. Raises httpx.HTTPError."""
    url = settings.PUBLIC_URL.rstrip("/") + "/api/latest-edition"
    response = (client or httpx.Client(timeout=TIMEOUT)).put(
        url,
        json={"subject": subject, "html": html, "text": text},
        headers={"Authorization": f"Bearer {settings.SUBSCRIBERS_API_TOKEN}"},
    )
    response.raise_for_status()


class LatestEdition(BaseModel):
    subject: str
    published_at: datetime
    text: str = ""

    @property
    def topic_titles(self) -> list[str]:
        """The "* title" lines of the plain-text "Notícias" section."""
        titles, in_news = [], False
        for line in self.text.splitlines():
            if line.startswith("== "):
                in_news = line.strip() == "== Notícias =="
            elif in_news and line.startswith("* "):
                titles.append(line[2:].strip())
        return titles


def latest_edition(settings: Settings, client: httpx.Client | None = None) -> LatestEdition | None:
    """Subject and send time of the page's last edition, None if none. Raises httpx.HTTPError."""
    url = settings.PUBLIC_URL.rstrip("/") + "/api/latest-edition"
    response = (client or httpx.Client(timeout=TIMEOUT)).get(
        url, headers={"Authorization": f"Bearer {settings.SUBSCRIBERS_API_TOKEN}"}
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return LatestEdition.model_validate(response.json())
