"""Window state store for NEXUS OS.

In-memory registry of all ``WindowState`` records, indexed by
``window_id``.  This is the single source of truth for what windows
exist and their logical properties on the Python side.

The store is intentionally *not* async — it is a simple dict-backed
registry that the ``WindowAgent`` reads and writes synchronously
within its own async ``execute`` method.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from core.vr_types import WindowState

logger = logging.getLogger("nexus.window_state_store")


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

@runtime_checkable
class IWindowStateStore(Protocol):
    """Protocol that any window state persistence backend must satisfy.

    The default implementation is ``WindowStateStore`` (in-memory dict).
    A future implementation could back this with SQLite or Redis.
    """

    def create(self, state: WindowState) -> WindowState: ...
    def get(self, window_id: str) -> WindowState | None: ...
    def get_by_workspace(self, workspace_id: str) -> list[WindowState]: ...
    def get_by_app(self, app_id: str) -> list[WindowState]: ...
    def get_focused(self) -> WindowState | None: ...
    def update(self, window_id: str, **fields: Any) -> WindowState: ...
    def remove(self, window_id: str) -> bool: ...
    def list_all(self) -> list[WindowState]: ...
    def count(self) -> int: ...


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

class WindowStateStore:
    """In-memory window state registry.

    Thread-safety note: NEXUS OS agents are single-threaded async, so
    no locking is needed.  If concurrency changes, wrap mutations in
    a lock.
    """

    def __init__(self) -> None:
        self._windows: dict[str, WindowState] = {}
        self._next_z_order: int = 1

    # ── create / read / update / delete ──────────────────────────────────

    def create(self, state: WindowState) -> WindowState:
        """Insert a new window into the store.

        Assigns a ``z_order`` automatically and ensures the ``window_id``
        is unique.

        Raises:
            ValueError: If a window with the same ``window_id`` already exists.
        """
        if state.window_id in self._windows:
            raise ValueError(f"Window '{state.window_id}' already exists")

        state.z_order = self._next_z_order
        self._next_z_order += 1
        state.created_at = datetime.now(timezone.utc)
        state.updated_at = state.created_at
        self._windows[state.window_id] = state

        logger.info(
            "Created window '%s' (title=%s, workspace=%s)",
            state.window_id,
            state.title,
            state.workspace_id,
        )
        return state

    def get(self, window_id: str) -> WindowState | None:
        """Retrieve a window by ID, or ``None`` if not found."""
        return self._windows.get(window_id)

    def get_by_workspace(self, workspace_id: str) -> list[WindowState]:
        """Return all windows in the given workspace, ordered by z_order."""
        return sorted(
            (w for w in self._windows.values() if w.workspace_id == workspace_id),
            key=lambda w: w.z_order,
        )

    def get_by_app(self, app_id: str) -> list[WindowState]:
        """Return all windows belonging to the given application."""
        return [
            w for w in self._windows.values()
            if w.app_id == app_id
        ]

    def get_focused(self) -> WindowState | None:
        """Return the currently focused window, or ``None``."""
        for w in self._windows.values():
            if w.is_focused:
                return w
        return None

    def update(self, window_id: str, **fields: Any) -> WindowState:
        """Update specific fields on an existing window.

        Automatically bumps ``updated_at``.

        Raises:
            KeyError: If the window does not exist.
        """
        window = self._windows.get(window_id)
        if window is None:
            raise KeyError(f"Window '{window_id}' not found")

        for key, value in fields.items():
            if not hasattr(window, key):
                logger.warning("Ignoring unknown field '%s' on WindowState", key)
                continue
            setattr(window, key, value)

        window.updated_at = datetime.now(timezone.utc)
        logger.debug("Updated window '%s': %s", window_id, list(fields.keys()))
        return window

    def remove(self, window_id: str) -> bool:
        """Remove a window from the store.  Returns True if it existed."""
        removed = self._windows.pop(window_id, None)
        if removed is not None:
            logger.info("Removed window '%s' (title=%s)", window_id, removed.title)
            return True
        return False

    # ── bulk queries ─────────────────────────────────────────────────────

    def list_all(self) -> list[WindowState]:
        """Return all windows, ordered by z_order."""
        return sorted(self._windows.values(), key=lambda w: w.z_order)

    def count(self) -> int:
        """Total number of tracked windows."""
        return len(self._windows)

    # ── focus management ─────────────────────────────────────────────────

    def set_focus(self, window_id: str) -> WindowState:
        """Focus the given window and unfocus all others.

        Returns the newly focused window.

        Raises:
            KeyError: If the window does not exist.
        """
        if window_id not in self._windows:
            raise KeyError(f"Window '{window_id}' not found")

        for wid, w in self._windows.items():
            if w.is_focused and wid != window_id:
                w.is_focused = False
                w.updated_at = datetime.now(timezone.utc)

        target = self._windows[window_id]
        target.is_focused = True
        target.z_order = self._next_z_order
        self._next_z_order += 1
        target.updated_at = datetime.now(timezone.utc)

        logger.info("Focused window '%s' (title=%s)", window_id, target.title)
        return target

    def unfocus_all(self) -> None:
        """Unfocus every window."""
        for w in self._windows.values():
            if w.is_focused:
                w.is_focused = False
                w.updated_at = datetime.now(timezone.utc)

    # ── introspection ────────────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        """Return a serialisable snapshot for diagnostics / API."""
        return {
            "total_windows": self.count(),
            "focused_window": (f := self.get_focused()) and f.window_id,
            "windows": [
                {
                    "window_id": w.window_id,
                    "title": w.title,
                    "app_id": w.app_id,
                    "workspace_id": w.workspace_id,
                    "is_focused": w.is_focused,
                    "content_type": w.content_type.value,
                }
                for w in self.list_all()
            ],
        }
