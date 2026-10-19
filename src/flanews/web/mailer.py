"""Confirmation e-mail sent when someone signs up."""

import logging
from pathlib import Path
from typing import Protocol

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from flanews.config import Settings
from flanews.send.recipients import Recipient
from flanews.send.resend_sender import ResendSender, SendError

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
SUBJECT = "Confirme sua inscrição no Urubu News"
TEMPLATES = Path(__file__).parent / "templates"


class MailError(Exception):
    """Raised when the confirmation e-mail cannot be sent."""


class Mailer(Protocol):
    def send_confirmation(self, email: str, confirm_url: str) -> None: ...

    def send_edition(
        self, email: str, subject: str, html: str, text: str, unsubscribe_url: str
    ) -> None: ...

    def send_notification(self, to: str, subject: str, text: str) -> None: ...


_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
)


class ResendConfirmationMailer:
    def __init__(
        self,
        api_key: str,
        sender: str,
        public_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.sender = sender
        self.public_url = public_url
        self._client = client or httpx.Client(timeout=15.0)

    def send_confirmation(self, email: str, confirm_url: str) -> None:
        context = {"confirm_url": confirm_url, "public_url": self.public_url}
        payload = {
            "from": self.sender,
            "to": [email],
            "subject": SUBJECT,
            "html": _env.get_template("email/confirm.html.j2").render(context),
            "text": _env.get_template("email/confirm.txt.j2").render(context),
        }
        try:
            response = self._client.post(
                RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailError(f"Resend rejected the e-mail: {_message(e.response)}") from e
        except httpx.TransportError as e:
            raise MailError(f"Could not reach Resend: {e}") from e
        logger.info("Confirmation sent (id=%s)", response.json().get("id"))

    def send_edition(
        self, email: str, subject: str, html: str, text: str, unsubscribe_url: str
    ) -> None:
        """Welcome a new subscriber with the latest edition, same path as the newsletter."""
        sender = ResendSender(self.api_key, self.sender, dry_run=False, client=self._client)
        try:
            sender.send(subject, html, text, [Recipient(email, unsubscribe_url)])
        except SendError as e:
            raise MailError(str(e)) from e

    def send_notification(self, to: str, subject: str, text: str) -> None:
        """Plain-text notice to the owner (new subscriber)."""
        payload = {"from": self.sender, "to": [to], "subject": subject, "text": text}
        try:
            response = self._client.post(
                RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailError(f"Resend rejected the e-mail: {_message(e.response)}") from e
        except httpx.TransportError as e:
            raise MailError(f"Could not reach Resend: {e}") from e


class LogMailer:
    """Local development without RESEND_API_KEY: the link goes to the log."""

    def send_confirmation(self, email: str, confirm_url: str) -> None:
        logger.warning("RESEND_API_KEY not set; confirmation link for %s: %s", email, confirm_url)

    def send_edition(
        self, email: str, subject: str, html: str, text: str, unsubscribe_url: str
    ) -> None:
        logger.warning("RESEND_API_KEY not set; would send %r to %s", subject, email)

    def send_notification(self, to: str, subject: str, text: str) -> None:
        logger.warning("RESEND_API_KEY not set; would notify %s: %s", to, subject)


def mailer_from_settings(settings: Settings) -> Mailer:
    if not settings.RESEND_API_KEY:
        return LogMailer()
    return ResendConfirmationMailer(
        settings.RESEND_API_KEY, settings.NEWSLETTER_FROM, settings.PUBLIC_URL
    )


def _message(response: httpx.Response) -> str:
    try:
        return response.json().get("message") or response.text
    except ValueError:
        return response.text
