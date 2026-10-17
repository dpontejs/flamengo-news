"""Subscribers kept in SQLite: pending until the e-mail is confirmed, then active."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

CONFIRMATION_COOLDOWN = timedelta(minutes=10)
# Data minimization: unconfirmed sign-ups and unsubscribed addresses are deleted after this.
RETENTION = timedelta(days=30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    email TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'unsubscribed')),
    created_at TEXT NOT NULL,
    confirmation_sent_at TEXT,
    confirmed_at TEXT,
    unsubscribed_at TEXT
);
CREATE TABLE IF NOT EXISTS editions (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    subject TEXT NOT NULL,
    html TEXT NOT NULL,
    text TEXT NOT NULL,
    published_at TEXT NOT NULL
);
"""


class RequestResult(Enum):
    SEND_CONFIRMATION = "send_confirmation"
    COOLDOWN = "cooldown"
    ALREADY_ACTIVE = "already_active"


@dataclass(frozen=True)
class Edition:
    """Last edition sent, with the unsubscribe placeholder still in it."""

    subject: str
    html: str
    text: str
    published_at: datetime


@dataclass(frozen=True)
class Subscriber:
    email: str
    status: str


def normalize(email: str) -> str:
    return email.strip().lower()


class SubscriberStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _run(self, sql: str, *params: object) -> list[tuple]:
        # `with connection` commits; `closing` releases the file handle.
        with closing(self._connect()) as db, db:
            return db.execute(sql, params).fetchall()

    def get(self, email: str) -> Subscriber | None:
        rows = self._run("SELECT email, status FROM subscribers WHERE email = ?", normalize(email))
        return Subscriber(*rows[0]) if rows else None

    def request(self, email: str, now: datetime) -> RequestResult:
        """Register a sign-up; tells whether a confirmation e-mail should go out."""
        email = normalize(email)
        rows = self._run(
            "SELECT status, confirmation_sent_at FROM subscribers WHERE email = ?", email
        )
        if not rows:
            self._run(
                "INSERT INTO subscribers (email, status, created_at, confirmation_sent_at)"
                " VALUES (?, 'pending', ?, ?)",
                email,
                now.isoformat(),
                now.isoformat(),
            )
            return RequestResult.SEND_CONFIRMATION

        status, sent_at = rows[0]
        if status == "active":
            return RequestResult.ALREADY_ACTIVE
        if (
            status == "pending"
            and sent_at
            and now - datetime.fromisoformat(sent_at) < CONFIRMATION_COOLDOWN
        ):
            return RequestResult.COOLDOWN
        self._run(
            "UPDATE subscribers SET status = 'pending', confirmation_sent_at = ? WHERE email = ?",
            now.isoformat(),
            email,
        )
        return RequestResult.SEND_CONFIRMATION

    def forget_confirmation(self, email: str) -> None:
        """Lift the cooldown after a confirmation e-mail failed to go out."""
        self._run(
            "UPDATE subscribers SET confirmation_sent_at = NULL WHERE email = ?", normalize(email)
        )

    def confirm(self, email: str, now: datetime) -> bool:
        """Activate a pending sign-up. An unsubscribed address needs a new sign-up first."""
        email = normalize(email)
        self._run(
            "UPDATE subscribers SET status = 'active', confirmed_at = ?"
            " WHERE email = ? AND status = 'pending'",
            now.isoformat(),
            email,
        )
        subscriber = self.get(email)
        return subscriber is not None and subscriber.status == "active"

    def unsubscribe(self, email: str, now: datetime) -> None:
        self._run(
            "UPDATE subscribers SET status = 'unsubscribed', unsubscribed_at = ?"
            " WHERE email = ? AND status != 'unsubscribed'",
            now.isoformat(),
            normalize(email),
        )

    def active(self) -> list[str]:
        rows = self._run(
            "SELECT email FROM subscribers WHERE status = 'active' ORDER BY confirmed_at, email"
        )
        return [email for (email,) in rows]

    def set_latest_edition(self, subject: str, html: str, text: str, now: datetime) -> None:
        self._run(
            "INSERT INTO editions (id, subject, html, text, published_at) VALUES (1, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET subject = excluded.subject, html = excluded.html,"
            " text = excluded.text, published_at = excluded.published_at",
            subject,
            html,
            text,
            now.isoformat(),
        )

    def latest_edition(self) -> Edition | None:
        rows = self._run("SELECT subject, html, text, published_at FROM editions WHERE id = 1")
        if not rows:
            return None
        subject, html, text, published_at = rows[0]
        return Edition(subject, html, text, datetime.fromisoformat(published_at))

    def confirmations_sent_since(self, since: datetime) -> int:
        rows = self._run(
            "SELECT COUNT(*) FROM subscribers WHERE confirmation_sent_at >= ?", since.isoformat()
        )
        return rows[0][0]

    def purge(self, now: datetime) -> int:
        """Delete stale pending sign-ups and old unsubscribes; returns how many were removed."""
        cutoff = (now - RETENTION).isoformat()
        rows = self._run(
            "DELETE FROM subscribers WHERE"
            " (status = 'pending' AND COALESCE(confirmation_sent_at, created_at) < ?)"
            " OR (status = 'unsubscribed' AND unsubscribed_at < ?)"
            " RETURNING email",
            cutoff,
            cutoff,
        )
        return len(rows)
