"""Signed, stateless tokens for confirmation and unsubscribe links.

Format: base64url(email) . base64url(issued_at) . base64url(hmac_sha256(purpose|email|issued_at)).
"""

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, purpose: str, email: str, issued_at: int) -> bytes:
    message = f"{purpose}|{email}|{issued_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).digest()


def make_token(secret: str, purpose: str, email: str, now: datetime) -> str:
    issued_at = int(now.timestamp())
    parts = (email.encode(), str(issued_at).encode(), _signature(secret, purpose, email, issued_at))
    return ".".join(_encode(p) for p in parts)


def read_token(
    secret: str,
    purpose: str,
    token: str,
    now: datetime,
    max_age: timedelta | None = None,
) -> str | None:
    """Return the e-mail inside a valid token, or None if it is forged, malformed or expired."""
    try:
        email_part, issued_part, signature_part = token.split(".")
        email = _decode(email_part).decode()
        issued_at = int(_decode(issued_part).decode())
        signature = _decode(signature_part)
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(signature, _signature(secret, purpose, email, issued_at)):
        return None
    if max_age is not None and now - datetime.fromtimestamp(issued_at, UTC) > max_age:
        return None
    return email
