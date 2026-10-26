"""Ephemeral local session authentication for NEXUS OS.

Sessions are intentionally process-local.  Only a SHA-256 digest of each
bearer token is retained, and the plaintext token is returned at creation
time only.  This is suitable for the single-process local development
deployment; it is not distributed authentication and does not survive a
process restart.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4


UTCNow = Callable[[], datetime]


@dataclass(frozen=True)
class AuthenticatedSession:
    """Public session identity returned after successful authentication."""

    session_id: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True)
class CreatedSession:
    """Session creation result containing the token exactly once."""

    session: AuthenticatedSession
    token: str


@dataclass
class _SessionRecord:
    session: AuthenticatedSession
    token_digest: bytes


class InvalidSessionToken(ValueError):
    """Raised when a bearer token is unknown, malformed, expired, or revoked."""


class SessionManager:
    """Thread-safe, in-memory manager for ephemeral local bearer sessions."""

    def __init__(
        self,
        lifetime_seconds: int = 3600,
        *,
        token_bytes: int = 32,
        clock: UTCNow | None = None,
    ) -> None:
        if lifetime_seconds <= 0:
            raise ValueError("lifetime_seconds must be positive")
        if token_bytes < 32:
            raise ValueError("token_bytes must be at least 32")
        self.lifetime = timedelta(seconds=lifetime_seconds)
        self._token_bytes = token_bytes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, _SessionRecord] = {}
        self._lock = threading.RLock()

    def create_session(self) -> CreatedSession:
        """Create a local session and return its plaintext token once."""
        now = self._now()
        token = secrets.token_urlsafe(self._token_bytes)
        session = AuthenticatedSession(
            session_id=f"sess_{uuid4().hex}",
            created_at=now,
            expires_at=now + self.lifetime,
        )
        record = _SessionRecord(session=session, token_digest=self._digest(token))
        with self._lock:
            self._cleanup_locked(now)
            self._sessions[session.session_id] = record
        return CreatedSession(session=session, token=token)

    def resolve(self, token: str) -> AuthenticatedSession:
        """Resolve a valid token without exposing stored token material."""
        if not isinstance(token, str) or not token or len(token) > 512:
            raise InvalidSessionToken("invalid session token")

        digest = self._digest(token)
        now = self._now()
        with self._lock:
            self._cleanup_locked(now)
            for record in self._sessions.values():
                if secrets.compare_digest(record.token_digest, digest):
                    if record.session.revoked or record.session.expires_at <= now:
                        raise InvalidSessionToken("invalid session token")
                    return record.session
        raise InvalidSessionToken("invalid session token")

    def revoke(self, session_id: str) -> bool:
        """Revoke a session immediately; return whether it existed."""
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return False
            record.session = AuthenticatedSession(
                session_id=record.session.session_id,
                created_at=record.session.created_at,
                expires_at=record.session.expires_at,
                revoked=True,
            )
            return True

    def cleanup_expired(self) -> int:
        """Remove expired sessions and return the number removed."""
        with self._lock:
            return self._cleanup_locked(self._now())

    def _cleanup_locked(self, now: datetime) -> int:
        expired = [
            session_id
            for session_id, record in self._sessions.items()
            if record.session.expires_at <= now or record.session.revoked
        ]
        for session_id in expired:
            del self._sessions[session_id]
        return len(expired)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("session clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()
