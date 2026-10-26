"""In-memory window state store.

The ``WindowAgent`` mutates this registry.  Read-only snapshots are
available for the Supervisor, HUD, and IPC bridge.

Design notes
────────────
* The registry is the *only* place where ``VRWindow`` records live on
  the Python side.
* A focus stack tracks most-recent-focus ordering so the agent can
  answer "which window is on top?" without querying Unity.
* All mutating methods return the affected window so callers can
  chain or inspect the result.
"""

from __future__ import annotations

import logging
from typing import Iterator

from vr.window_types import VRWindow, WindowState

logger = logging.getLogger("nexus.vr.window_registry")


class WindowRegistry:
    """Central store for all active VRWindow records.

    Thread-safety note: in the current single-threaded asyncio design,
    no locking is needed.  If NEXUS OS ever moves to multi-threaded
    agents, this class should be wrapped with a lock.
    """

    def __init__(self) -> None:
        self._windows: dict[str, VRWindow] = {}
        self._focus_stack: list[str] = []       # ordered: oldest → newest focus
        self._next_z_order: int = 1

    # ── CRUD ─────────────────────────────────────────────────────────────

    def add(self, window: VRWindow) -> None:
        """Register a new window.  Appends it to the focus stack."""
        window.z_order = self._next_z_order
        self._next_z_order += 1
        self._windows[window.window_id] = window
        self._focus_stack.append(window.window_id)
        logger.info("Registered window: %s (%s)", window.window_id, window.title)

    def remove(self, window_id: str) -> VRWindow | None:
        """Remove and return a window, or ``None`` if not found."""
        win = self._windows.pop(window_id, None)
        if window_id in self._focus_stack:
            self._focus_stack.remove(window_id)
        if win:
            logger.info("Removed window: %s (%s)", window_id, win.title)
        return win

    def get(self, window_id: str) -> VRWindow | None:
        """Look up a window by ID."""
        return self._windows.get(window_id)

    def update(self, window: VRWindow) -> None:
        """Replace the stored record for an existing window."""
        if window.window_id in self._windows:
            self._windows[window.window_id] = window

    # ── Queries ──────────────────────────────────────────────────────────

    def get_all(self) -> list[VRWindow]:
        """Return all windows (insertion order)."""
        return list(self._windows.values())

    def get_by_workspace(self, workspace_index: int) -> list[VRWindow]:
        """Return windows belonging to a specific workspace."""
        return [
            w for w in self._windows.values()
            if w.workspace_index == workspace_index
        ]

    def get_by_app(self, app_id: str) -> list[VRWindow]:
        """Return all windows linked to a specific application."""
        return [w for w in self._windows.values() if w.app_id == app_id]

    def get_focused(self) -> VRWindow | None:
        """Return the currently focused window (top of focus stack)."""
        for wid in reversed(self._focus_stack):
            win = self._windows.get(wid)
            if win and win.is_focused:
                return win
        return None

    def get_open_count(self) -> int:
        """Count windows that are visibly open (OPEN or MAXIMIZED)."""
        return sum(
            1 for w in self._windows.values()
            if w.state in (WindowState.OPEN, WindowState.MAXIMIZED)
        )

    def get_by_state(self, state: WindowState) -> list[VRWindow]:
        """Return all windows in a given lifecycle state."""
        return [w for w in self._windows.values() if w.state == state]

    # ── Focus Management ─────────────────────────────────────────────────

    def set_focus(self, window_id: str) -> VRWindow | None:
        """Bring *window_id* to the top of the focus stack.

        Unfocuses all other windows and assigns the highest z-order
        to the newly focused window.

        Returns:
            The focused window, or ``None`` if *window_id* was not found.
        """
        # Unfocus everything
        for w in self._windows.values():
            w.is_focused = False

        win = self._windows.get(window_id)
        if win is None:
            return None

        win.is_focused = True
        win.z_order = self._next_z_order
        self._next_z_order += 1

        # Move to top of focus stack
        if window_id in self._focus_stack:
            self._focus_stack.remove(window_id)
        self._focus_stack.append(window_id)

        logger.debug("Focus set: %s (%s)", window_id, win.title)
        return win

    def clear_focus(self) -> None:
        """Unfocus all windows."""
        for w in self._windows.values():
            w.is_focused = False

    # ── Bulk Operations ──────────────────────────────────────────────────

    def close_all_in_workspace(self, workspace_index: int) -> list[VRWindow]:
        """Mark all windows in a workspace as CLOSING and return them."""
        targets = self.get_by_workspace(workspace_index)
        for w in targets:
            w.state = WindowState.CLOSING
        return targets

    def clear(self) -> None:
        """Remove all windows.  Useful in tests."""
        self._windows.clear()
        self._focus_stack.clear()
        self._next_z_order = 1
        logger.info("Window registry cleared")

    # ── Introspection ────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._windows)

    def __iter__(self) -> Iterator[VRWindow]:
        return iter(self._windows.values())

    def __contains__(self, window_id: str) -> bool:
        return window_id in self._windows

    def describe(self) -> list[dict]:
        """Return serializable snapshots for every window."""
        return [w.model_dump(mode="json") for w in self._windows.values()]
