import html as html_lib
import logging
import uuid

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
from flanews.send.recipients import Recipient

logger = logging.getLogger(__name__)

RESEND_BATCH_URL = "https://api.resend.com/emails/batch"
BATCH_SIZE = 100  # Resend's limit per batch call
MAX_ATTEMPTS = 3
TIMEOUT = 30.0
# Rendered in place of the unsubscribe link, then swapped for each recipient's own link.
UNSUBSCRIBE_PLACEHOLDER = "https://unsubscribe.invalid/recipient"


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
    """Sends the newsletter through Resend's batch API (no SDK), one e-mail per recipient.

    Each e-mail carries the recipient's own unsubscribe link (footer and List-Unsubscribe
    headers). With `dry_run` nothing is sent and the call is only logged.
    """

    def __init__(
        self,
        api_key: str | None,
        sender: str,
        dry_run: bool = True,
        client: httpx.Client | None = None,
        wait: wait_base | None = None,
    ) -> None:
        self.api_key = api_key
        self.sender = sender
        self.dry_run = dry_run
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._wait = wait or wait_exponential(multiplier=2, max=30)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResendSender":
        return cls(
            api_key=settings.RESEND_API_KEY,
            sender=settings.NEWSLETTER_FROM,
            dry_run=settings.DRY_RUN,
        )

    def send(self, subject: str, html: str, text: str, recipients: list[Recipient]) -> list[str]:
        """Send one e-mail per recipient and return Resend's ids (empty on dry run)."""
        if self.dry_run:
            logger.info("DRY_RUN: would send %r to %d recipients", subject, len(recipients))
            return []
        if not recipients:
            logger.warning("No recipients: nothing sent")
            return []
        if not self.api_key:
            raise SendError("RESEND_API_KEY is not configured")

        emails = [self._email(subject, html, text, r) for r in recipients]
        run_key = uuid.uuid4().hex
        ids: list[str] = []
        for start in range(0, len(emails), BATCH_SIZE):
            batch = emails[start : start + BATCH_SIZE]
            try:
                ids += self._send_batch(batch, f"{run_key}-{start // BATCH_SIZE}")
            except SendError as e:
                if ids:
                    raise SendError(f"{e} (sent to {len(ids)} of {len(emails)})") from e
                raise
        logger.info("Sent %r to %d recipients", subject, len(ids))
        return ids

    def _email(self, subject: str, html: str, text: str, recipient: Recipient) -> dict:
        url = recipient.unsubscribe_url
        headers = {"List-Unsubscribe": f"<{url}>"}
        if url.startswith("https://"):
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"  # RFC 8058
        return {
            "from": self.sender,
            "to": [recipient.email],
            "subject": subject,
            "html": html.replace(UNSUBSCRIBE_PLACEHOLDER, html_lib.escape(url)),
            "text": text.replace(UNSUBSCRIBE_PLACEHOLDER, url),
            "headers": headers,
        }

    def _send_batch(self, batch: list[dict], idempotency_key: str) -> list[str]:
        retrying = Retrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=self._wait,
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        try:
            response = retrying(self._post, batch, idempotency_key)
        except httpx.HTTPStatusError as e:
            raise SendError(f"Resend rejected the e-mail: {_error_message(e.response)}") from e
        except httpx.TransportError as e:
            raise SendError(f"Could not reach Resend: {e}") from e
        return [item.get("id") for item in response.json().get("data", [])]

    def _post(self, batch: list[dict], idempotency_key: str) -> httpx.Response:
        response = self._client.post(
            RESEND_BATCH_URL,
            json=batch,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                # Retries of the same batch never deliver twice.
                "Idempotency-Key": idempotency_key,
            },
        )
        response.raise_for_status()
        return response


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("message") or response.text
    except ValueError:
        return response.text
