"""Desktop environment context for NEXUS OS.

Tracks the live state of the user's desktop environment:

* **Active workspace** — which virtual desktop / workspace is focused.
* **Focused window** — the window that currently has input focus.
* **Active application** — the application owning the focused window.
* **Running applications** — all user-visible applications with their windows.
* **Recent user actions** — bounded log of the last N actions for
  pronoun/referent resolution (\"close *this*\", \"move *it* left\").

All data is structured as lightweight dataclasses to keep token usage
low when serialised into LLM context.  No external dependencies — the
tracker is populated via explicit ``update_*`` calls from tools, agents,
or OS event hooks.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("nexus.context.environment")

# ── Defaults ─────────────────────────────────────────────────────────────

MAX_RECENT_ACTIONS = 30
MAX_RUNNING_APPS = 50


# ── Data models ──────────────────────────────────────────────────────────

class ActionType(str, Enum):
    """Categories of user actions tracked for referent resolution."""

    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    FOCUS_WINDOW = "focus_window"
    FILE_OPERATION = "file_operation"
    NAVIGATION = "navigation"
    SYSTEM_QUERY = "system_query"
    COMMAND = "command"
    OTHER = "other"


@dataclass
class WindowInfo:
    """Lightweight snapshot of a single desktop window.

    Attributes:
        window_id:   OS-level window identifier (XID, Wayland handle, etc.).
        title:       Window title bar text.
        app_name:    Owning application name.
        workspace:   Workspace / virtual desktop index or name.
        is_focused:  Whether this window currently has input focus.
        is_minimized: Whether the window is minimized.
        pid:         Process ID of the owning application.
        geometry:    Optional ``{x, y, width, height}`` dict.
    """

    window_id: str = ""
    title: str = ""
    app_name: str = ""
    workspace: str = ""
    is_focused: bool = False
    is_minimized: bool = False
    pid: int = 0
    geometry: dict[str, int] = field(default_factory=dict)


@dataclass
class AppInfo:
    """Running application with its windows.

    Attributes:
        name:       Application name (e.g. ``"firefox"``).
        desktop_id: ``.desktop`` entry ID if known.
        pid:        Primary process ID.
        windows:    All windows owned by this application.
        started_at: Monotonic timestamp when first registered.
    """

    name: str = ""
    desktop_id: str = ""
    pid: int = 0
    windows: list[WindowInfo] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)


@dataclass
class WorkspaceInfo:
    """Virtual desktop / workspace metadata.

    Attributes:
        index: Zero-based workspace index.
        name:  Human-readable name (e.g. ``"Main"``, ``"Dev"``).
        is_active: Whether this workspace is currently displayed.
    """

    index: int = 0
    name: str = ""
    is_active: bool = False


@dataclass
class UserAction:
    """A single recorded user action for referent tracking.

    When the user says \"close *this*\", the resolver walks recent actions
    to find the most plausible referent.

    Attributes:
        action_type: Category of the action.
        description: Human-readable one-liner.
        subject:     The primary entity acted upon (app name, file path,
                     window title, etc.).
        subject_type: What kind of entity ``subject`` is
                      (``"app"``, ``"file"``, ``"window"``, ``"path"``).
        parameters:  Extra structured data about the action.
        timestamp:   Monotonic time when the action was recorded.
    """

    action_type: ActionType = ActionType.OTHER
    description: str = ""
    subject: str = ""
    subject_type: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


# ── Environment Tracker ─────────────────────────────────────────────────

class EnvironmentContext:
    """Live desktop environment state tracker.

    This is the central object that holds the user's current desktop
    context.  It is designed to be:

    * **Structured** — everything is a typed dataclass, not free-form dicts.
    * **Bounded** — action history is capped; app list is pruned.
    * **Serialisable** — ``snapshot()`` returns a compact dict that can
      go straight into an LLM system prompt without blowing the token
      budget.

    The tracker does **not** query the OS directly.  It is populated
    by external hooks (tools, agents, D-Bus listeners, …) calling its
    ``update_*`` / ``record_action`` methods.

    Parameters:
        max_recent_actions: Rolling limit for the action history.
        max_running_apps:   Cap on tracked running applications.
    """

    def __init__(
        self,
        max_recent_actions: int = MAX_RECENT_ACTIONS,
        max_running_apps: int = MAX_RUNNING_APPS,
    ) -> None:
        # Desktop state
        self._workspaces: list[WorkspaceInfo] = []
        self._focused_window: WindowInfo | None = None
        self._active_app: AppInfo | None = None
        self._running_apps: dict[str, AppInfo] = {}  # name → AppInfo

        # Action history (bounded)
        self._recent_actions: deque[UserAction] = deque(
            maxlen=max_recent_actions,
        )
        self._max_running_apps = max_running_apps

    # ── Workspace management ─────────────────────────────────────────────

    def update_workspaces(self, workspaces: list[WorkspaceInfo]) -> None:
        """Replace the full workspace list (e.g. from a WM query)."""
        self._workspaces = workspaces

    def set_active_workspace(self, index: int) -> None:
        """Mark workspace *index* as active, deactivating others."""
        for ws in self._workspaces:
            ws.is_active = (ws.index == index)

    @property
    def active_workspace(self) -> WorkspaceInfo | None:
        """The currently active workspace, or ``None``."""
        return next((ws for ws in self._workspaces if ws.is_active), None)

    # ── Focused window ───────────────────────────────────────────────────

    def update_focused_window(self, window: WindowInfo) -> None:
        """Set the currently focused window and derive the active app."""
        # De-focus old window
        if self._focused_window is not None:
            self._focused_window.is_focused = False
        window.is_focused = True
        self._focused_window = window

        # Derive active app from focused window
        if window.app_name and window.app_name in self._running_apps:
            self._active_app = self._running_apps[window.app_name]

    @property
    def focused_window(self) -> WindowInfo | None:
        return self._focused_window

    @property
    def active_app(self) -> AppInfo | None:
        return self._active_app

    # ── Running applications ─────────────────────────────────────────────

    def register_app(self, app: AppInfo) -> None:
        """Register (or update) a running application."""
        if len(self._running_apps) >= self._max_running_apps and app.name not in self._running_apps:
            # Evict oldest app by start time
            oldest_name = min(
                self._running_apps,
                key=lambda n: self._running_apps[n].started_at,
            )
            del self._running_apps[oldest_name]
            logger.debug("Evicted oldest tracked app: %s", oldest_name)

        self._running_apps[app.name] = app

    def unregister_app(self, name: str) -> None:
        """Remove an application from the running set."""
        self._running_apps.pop(name, None)
        # Clear active/focused references if they pointed to this app
        if self._active_app and self._active_app.name == name:
            self._active_app = None
        if self._focused_window and self._focused_window.app_name == name:
            self._focused_window = None

    def get_app(self, name: str) -> AppInfo | None:
        """Look up a running application by name (case-insensitive)."""
        key = name.lower()
        for app_name, app in self._running_apps.items():
            if app_name.lower() == key:
                return app
        return None

    @property
    def running_apps(self) -> dict[str, AppInfo]:
        """Read-only view of running applications."""
        return dict(self._running_apps)

    def update_running_apps(self, apps: list[AppInfo]) -> None:
        """Bulk-replace the running apps list (e.g. from a process scan)."""
        self._running_apps.clear()
        for app in apps[: self._max_running_apps]:
            self._running_apps[app.name] = app

    # ── Action recording ─────────────────────────────────────────────────

    def record_action(self, action: UserAction) -> None:
        """Append an action to the bounded history."""
        self._recent_actions.append(action)

    def record(
        self,
        action_type: ActionType,
        subject: str,
        subject_type: str = "",
        description: str = "",
        **params: Any,
    ) -> None:
        """Convenience wrapper to record an action in one call."""
        self._recent_actions.append(
            UserAction(
                action_type=action_type,
                subject=subject,
                subject_type=subject_type,
                description=description or f"{action_type.value}: {subject}",
                parameters=params,
            )
        )

    @property
    def recent_actions(self) -> list[UserAction]:
        """Return the action history as a plain list (oldest first)."""
        return list(self._recent_actions)

    # ── Referent resolution ──────────────────────────────────────────────

    def resolve_referent(
        self,
        pronoun: str,
        subject_type_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Attempt to resolve a pronoun (\"this\", \"it\", \"that\") to a
        concrete entity from the current environment context.

        Resolution priority:

        1. **\"this\"** → focused window → active app → last action subject.
        2. **\"it\"**   → last action subject → active app.
        3. **\"that\"** → second-to-last action subject → last action subject.

        Parameters:
            pronoun:           The pronoun to resolve (lowercased).
            subject_type_hint: Optional hint constraining the kind of
                               entity to look for (``"app"``, ``"file"``,
                               ``"window"``).

        Returns:
            A dict with keys ``subject``, ``subject_type``, ``source``
            describing the resolved entity, or ``None`` if resolution
            fails.
        """
        pronoun = pronoun.strip().lower()

        if pronoun == "this":
            return self._resolve_this(subject_type_hint)
        elif pronoun in ("it", "its"):
            return self._resolve_it(subject_type_hint)
        elif pronoun == "that":
            return self._resolve_that(subject_type_hint)
        else:
            # Unknown pronoun — try "it" heuristic
            return self._resolve_it(subject_type_hint)

    def _resolve_this(self, hint: str | None) -> dict[str, Any] | None:
        """\"this\" = the thing the user is currently looking at / using."""
        # 1. Focused window
        if self._focused_window and self._matches_hint(hint, "window"):
            return {
                "subject": self._focused_window.title or self._focused_window.app_name,
                "subject_type": "window",
                "source": "focused_window",
                "window": self._focused_window,
            }
        # 2. Active app
        if self._active_app and self._matches_hint(hint, "app"):
            return {
                "subject": self._active_app.name,
                "subject_type": "app",
                "source": "active_app",
            }
        # 3. Last action
        return self._from_last_action(0, hint)

    def _resolve_it(self, hint: str | None) -> dict[str, Any] | None:
        """\"it\" = the thing most recently acted upon."""
        # 1. Last action subject
        result = self._from_last_action(0, hint)
        if result:
            return result
        # 2. Active app fallback
        if self._active_app and self._matches_hint(hint, "app"):
            return {
                "subject": self._active_app.name,
                "subject_type": "app",
                "source": "active_app",
            }
        return None

    def _resolve_that(self, hint: str | None) -> dict[str, Any] | None:
        """\"that\" = the thing before the most recent action."""
        # 1. Second-to-last action
        result = self._from_last_action(1, hint)
        if result:
            return result
        # 2. Fall back to last action
        return self._from_last_action(0, hint)

    def _from_last_action(
        self,
        offset: int,
        hint: str | None,
    ) -> dict[str, Any] | None:
        """Extract a referent from the Nth-from-last action."""
        actions = self._recent_actions
        idx = len(actions) - 1 - offset
        if idx < 0:
            return None
        action = actions[idx]
        if hint and action.subject_type and action.subject_type != hint:
            # Hint mismatch — try scanning backwards
            for i in range(idx, -1, -1):
                if actions[i].subject_type == hint:
                    action = actions[i]
                    break
            else:
                return None
        if not action.subject:
            return None
        return {
            "subject": action.subject,
            "subject_type": action.subject_type,
            "source": f"action_history[{offset}]",
            "action": action,
        }

    @staticmethod
    def _matches_hint(hint: str | None, subject_type: str) -> bool:
        """Check if a type hint matches (or if no hint is given)."""
        if hint is None:
            return True
        return hint == subject_type

    # ── Snapshot (for LLM context injection) ──────────────────────────────

    def snapshot(self, max_actions: int = 10) -> dict[str, Any]:
        """Return a compact, structured snapshot of the environment.

        Designed to be injected into an LLM system message without
        blowing the token budget.  Only includes non-empty sections.

        Parameters:
            max_actions: How many recent actions to include.
        """
        snap: dict[str, Any] = {}

        # Active workspace
        ws = self.active_workspace
        if ws:
            snap["workspace"] = {"index": ws.index, "name": ws.name}

        # Focused window
        if self._focused_window:
            snap["focused_window"] = {
                "title": self._focused_window.title,
                "app": self._focused_window.app_name,
            }
            if self._focused_window.geometry:
                snap["focused_window"]["geometry"] = self._focused_window.geometry

        # Active application
        if self._active_app:
            snap["active_app"] = self._active_app.name

        # Running apps (names only — full window lists are too verbose)
        if self._running_apps:
            snap["running_apps"] = sorted(self._running_apps.keys())

        # Recent actions (most recent last, capped)
        actions = list(self._recent_actions)[-max_actions:]
        if actions:
            snap["recent_actions"] = [
                {
                    "action": a.action_type.value,
                    "subject": a.subject,
                    "type": a.subject_type,
                }
                for a in actions
            ]

        return snap

    # ── Reset ────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all tracked state."""
        self._workspaces.clear()
        self._focused_window = None
        self._active_app = None
        self._running_apps.clear()
        self._recent_actions.clear()
