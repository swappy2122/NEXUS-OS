"""Conversation memory store for NEXUS OS.

Maintains per-session chat history with automatic trimming to stay
within a token budget.  For the prototype this is in-memory only;
swap the backing store for SQLite later without changing the API.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger("NEXUS_OS.context.conversation")

# Rough token estimate: 1 token ≈ 4 chars (good enough for budgeting)
CHARS_PER_TOKEN = 4


class ConversationStore:
    """In-memory conversation history keyed by session ID.

    Each session holds an ordered list of messages in the standard
    ``{"role": ..., "content": ...}`` format.
    """

    def __init__(self, default_max_tokens: int = 8192) -> None:
        self._sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._default_max_tokens = default_max_tokens

    # -- write -------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append a message to the session history."""
        self._sessions[session_id].append({"role": role, "content": content})

    # -- read --------------------------------------------------------------

    def get_history(
        self,
        session_id: str,
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        """Return the most recent messages that fit within *max_tokens*.

        Messages are returned in chronological order.  If the full
        history exceeds the token budget, older messages are dropped
        from the front.
        """
        budget = max_tokens or self._default_max_tokens
        budget_chars = budget * CHARS_PER_TOKEN

        messages = self._sessions.get(session_id, [])
        result: list[dict[str, str]] = []
        total_chars = 0

        # Walk backwards (most recent first) and collect until budget hit
        for msg in reversed(messages):
            msg_chars = len(msg.get("content", ""))
            if total_chars + msg_chars > budget_chars and result:
                break
            result.append(msg)
            total_chars += msg_chars

        result.reverse()
        return result

    # -- management --------------------------------------------------------

    def clear_session(self, session_id: str) -> None:
        """Delete all messages for a session."""
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())

    @property
    def session_count(self) -> int:
        return len(self._sessions)
