"""Context manager for NEXUS OS.

Provides a unified interface to the four context layers:

1. **Conversation** — per-session chat history
2. **System state** — CWD, recent tool results, etc.
3. **Environment** — desktop state: workspace, focused window,
   active app, running apps, action history
4. **Referent resolver** — pronoun resolution (\"close *this*\")

The Supervisor injects a context snapshot into every task it dispatches
to a specialized agent by calling ``build_snapshot()``.  It can also
pre-process user intent via ``resolve_intent()`` to replace deictic
pronouns before routing.
"""

from __future__ import annotations

import logging
from typing import Any

from context.conversation import ConversationStore
from context.environment import (
    ActionType,
    AppInfo,
    EnvironmentContext,
    UserAction,
    WindowInfo,
    WorkspaceInfo,
)
from context.referent_resolver import ReferentResolver, ResolutionResult
from context.system_state import SystemState
from core.types import ToolResult

logger = logging.getLogger("NEXUS_OS.context")


class ContextManager:
    """Unified context façade used by agents and the supervisor.

    Parameters:
        max_history_tokens: Default token budget for conversation history.
        max_recent_actions: Rolling limit for environment action history.
    """

    def __init__(
        self,
        max_history_tokens: int = 8192,
        max_recent_actions: int = 30,
    ) -> None:
        self.conversation = ConversationStore(
            default_max_tokens=max_history_tokens,
        )
        self.system = SystemState()
        self.environment = EnvironmentContext(
            max_recent_actions=max_recent_actions,
        )
        self.referent_resolver = ReferentResolver(self.environment)

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

    # -- environment shortcuts ---------------------------------------------

    def update_focused_window(self, window: WindowInfo) -> None:
        """Update which window has focus — also sets the active app."""
        self.environment.update_focused_window(window)

    def register_app(self, app: AppInfo) -> None:
        """Track a running application."""
        self.environment.register_app(app)

    def unregister_app(self, name: str) -> None:
        """Remove an application from the running set."""
        self.environment.unregister_app(name)

    def update_workspaces(self, workspaces: list[WorkspaceInfo]) -> None:
        """Replace workspace metadata."""
        self.environment.update_workspaces(workspaces)

    def set_active_workspace(self, index: int) -> None:
        """Switch the active workspace."""
        self.environment.set_active_workspace(index)

    def record_action(
        self,
        action_type: ActionType,
        subject: str,
        subject_type: str = "",
        description: str = "",
        **params: Any,
    ) -> None:
        """Record a user action for referent resolution."""
        self.environment.record(
            action_type=action_type,
            subject=subject,
            subject_type=subject_type,
            description=description,
            **params,
        )

    # -- referent resolution -----------------------------------------------

    def resolve_intent(self, intent: str) -> ResolutionResult:
        """Resolve pronouns in *intent* using the environment context.

        Call this before routing to replace \"this\", \"it\", \"that\"
        with concrete entity names.
        """
        return self.referent_resolver.resolve(intent)

    def has_pronouns(self, intent: str) -> bool:
        """Quick check for resolvable pronouns in *intent*."""
        return self.referent_resolver.has_pronouns(intent)

    # -- composite snapshot ------------------------------------------------

    def build_snapshot(
        self,
        session_id: str,
        history_tokens: int = 2048,
        max_env_actions: int = 10,
    ) -> dict[str, Any]:
        """Build a combined context snapshot for task dispatch.

        The Supervisor calls this before handing a sub-task to a
        specialized agent.  The snapshot is compact and bounded to
        control token usage.

        Sections included:
        - ``conversation``: trimmed message history
        - ``system``: CWD, recent tool results
        - ``environment``: workspace, focused window, active app,
          running apps, recent actions
        """
        return {
            "conversation": self.get_history(session_id, max_tokens=history_tokens),
            "system": self.get_system_snapshot(),
            "environment": self.environment.snapshot(max_actions=max_env_actions),
        }
