"""Context manager for NEXUS OS.

Provides a unified interface to the three context layers:

1. **Conversation** — per-session chat history
2. **System state** — CWD, recent tool results, etc.
3. **Spatial state** — VR head/hand position (future)

The Supervisor injects a context snapshot into every task it dispatches
to a specialized agent by calling ``build_snapshot()``.
"""

from __future__ import annotations

import logging
from typing import Any

from context.conversation import ConversationStore
from context.system_state import SystemState
from core.types import ToolResult

logger = logging.getLogger("NEXUS_OS.context")


class ContextManager:
    """Unified context façade used by agents and the supervisor.

    Parameters:
        max_history_tokens: Default token budget for conversation history.
    """

    def __init__(self, max_history_tokens: int = 8192) -> None:
        self.conversation = ConversationStore(
            default_max_tokens=max_history_tokens,
        )
        self.system = SystemState()

    # -- conversation shortcuts --------------------------------------------

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Record a message in the conversation history."""
        self.conversation.add_message(session_id, role, content)

    def get_history(
        self,
        session_id: str,
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve recent conversation history within a token budget."""
        return self.conversation.get_history(session_id, max_tokens)

    # -- system shortcuts --------------------------------------------------

    def update_system_state(self, key: str, value: Any) -> None:
        self.system.update(key, value)

    def get_system_snapshot(self) -> dict[str, Any]:
        return self.system.snapshot()

    def cache_tool_result(self, result: ToolResult) -> None:
        self.system.cache_tool_result(result)

    # -- composite snapshot ------------------------------------------------

    def build_snapshot(
        self,
        session_id: str,
        history_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Build a combined context snapshot for task dispatch.

        The Supervisor calls this before handing a sub-task to a
        specialized agent.
        """
        return {
            "conversation": self.get_history(session_id, max_tokens=history_tokens),
            "system": self.get_system_snapshot(),
        }
