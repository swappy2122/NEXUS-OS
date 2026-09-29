"""System state tracker for NEXUS OS.

Tracks ephemeral OS-level state that agents may need — current working
directory, open files, recent tool results, etc.  For the prototype
this is a simple dict wrapper; it could later be backed by procfs
watchers or D-Bus listeners.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any

from core.types import ToolResult


class SystemState:
    """In-memory snapshot of system-level state relevant to agents.

    Attributes:
        cwd: Current working directory.
        env_vars: Subset of environment variables exposed to agents.
        recent_tool_results: Rolling cache of the last N tool results.
    """

    def __init__(self, max_recent_results: int = 20) -> None:
        self._state: dict[str, Any] = {
            "cwd": os.getcwd(),
        }
        self._recent_results: deque[dict[str, Any]] = deque(
            maxlen=max_recent_results,
        )

    # -- key/value state ---------------------------------------------------

    def update(self, key: str, value: Any) -> None:
        """Set or update a state key."""
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a state value."""
        return self._state.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the full state dict."""
        return {
            **self._state,
            "recent_tool_results": list(self._recent_results),
        }

    # -- tool result cache -------------------------------------------------

    def cache_tool_result(self, result: ToolResult) -> None:
        """Append a tool result to the rolling cache."""
        self._recent_results.append({
            "tool": result.tool_name,
            "success": result.success,
            "output_preview": str(result.output)[:200] if result.output else "",
        })

    def get_recent_results(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most recent cached tool results."""
        return list(self._recent_results)[-limit:]
