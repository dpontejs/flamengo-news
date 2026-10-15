import logging
from email.utils import parseaddr

import httpx
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from flanews.config import Settings
from flanews.models import Newsletter

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
MAX_ATTEMPTS = 3
TIMEOUT = 30.0


class SendError(Exception):
    """Raised when the newsletter cannot be delivered."""


def build_subject(newsletter: Newsletter) -> str:
    subject = f"Flamengo News — {newsletter.edition.label}"
    return f"{subject}: {newsletter.headline}" if newsletter.headline else subject


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return isinstance(error, httpx.TransportError)


class ResendSender:
    """Sends the newsletter through Resend's HTTP API (no SDK).

    The sender address goes in `to` and subscribers in `bcc`, so recipients do not
    see each other. With `dry_run` nothing is sent and the call is only logged.
    """

    def __init__(
        self,
        api_key: str | None,
        sender: str,
        recipients: list[str],
        dry_run: bool = True,
        client: httpx.Client | None = None,
        wait: wait_base | None = None,
    ) -> None:
        self.api_key = api_key
        self.sender = sender
        self.recipients = recipients
        self.dry_run = dry_run
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._wait = wait or wait_exponential(multiplier=2, max=30)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResendSender":
        return cls(
            api_key=settings.RESEND_API_KEY,
            sender=settings.NEWSLETTER_FROM,
            recipients=list(settings.NEWSLETTER_RECIPIENTS),
            dry_run=settings.DRY_RUN,
        )

    def send(self, subject: str, html: str, text: str, unsubscribe_url: str) -> str | None:
        """Send the e-mail and return Resend's id (None on dry run)."""
        if self.dry_run:
            logger.info("DRY_RUN: would send %r to %d recipients", subject, len(self.recipients))
            return None
        if not self.api_key:
            raise SendError("RESEND_API_KEY is not configured")

        _, sender_address = parseaddr(self.sender)
        payload = {
            "from": self.sender,
            "to": [sender_address],
            "bcc": self.recipients,
            "subject": subject,
            "html": html,
            "text": text,
            "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        }
        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=self._wait,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        try:
            response = retrying(self._post, payload)
        except httpx.HTTPStatusError as e:
            raise SendError(f"Resend rejected the e-mail: {_error_message(e.response)}") from e
        except httpx.TransportError as e:
            raise SendError(f"Could not reach Resend: {e}") from e

        email_id = response.json().get("id")
        logger.info("Sent %r to %d recipients (id=%s)", subject, len(self.recipients), email_id)
        return email_id

    def _post(self, payload: dict) -> httpx.Response:
        response = self._client.post(
            RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        response.raise_for_status()
        return response


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("message") or response.text
    except ValueError:
        return response.text
