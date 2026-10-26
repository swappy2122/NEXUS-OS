"""Window agent for NEXUS OS.

Manages the logical lifecycle of VR spatial windows: creation, destruction,
spatial transformations (move, resize, rotate), focus management, and
layout orchestration.

The WindowAgent owns the *logical* state via ``WindowRegistry``.  It
publishes ``WindowCommand`` events through the ``EventBus`` which the
``VRBridge`` serializes and forwards to Unity.  It does **not** render
anything or touch Unity APIs directly.

Communication flow
──────────────────
  Supervisor ──→ WindowAgent.execute(ctx)
                   ├── mutates WindowRegistry
                   ├── publishes to EventBus ("window.command.*")
                   └── VRBridge serializes → Unity
"""

from __future__ import annotations

import logging
import math
from typing import Any

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, Capability
from core.event_bus import EventBus

from vr.window_protocol import (
    CreatePayload,
    FocusPayload,
    MovePayload,
    ResizePayload,
    RotatePayload,
    SetStatePayload,
    WindowCommand,
    WindowCommandType,
    WindowEvent,
    WindowEventType,
    build_command,
)
from vr.window_registry import WindowRegistry
from vr.window_types import (
    Quat,
    Vec3,
    VRWindow,
    WindowAnchor,
    WindowSize,
    WindowState,
    WindowTransform,
)

logger = logging.getLogger("nexus.agent.window")


# ── Capability declarations ─────────────────────────────────────────────

WINDOW_CAPABILITIES = [
    Capability(name="window_create", description="Create a new VR spatial window"),
    Capability(name="window_close", description="Close/destroy a VR window"),
    Capability(name="window_move", description="Reposition a window in 3D space"),
    Capability(name="window_resize", description="Change a window's spatial dimensions"),
    Capability(name="window_rotate", description="Rotate a window's orientation"),
    Capability(name="window_focus", description="Bring a window to the foreground"),
    Capability(name="window_list", description="List active VR windows"),
    Capability(name="window_layout", description="Arrange windows in spatial layouts"),
]

# ── Spatial constants ───────────────────────────────────────────────────

# Default comfort-zone parameters (meters)
_DEFAULT_RADIUS = 2.5        # distance from user
_DEFAULT_HEIGHT = 1.5        # eye-level baseline
_ARC_HALF_ANGLE = 45.0       # degrees, ±45° from center
_GRID_COLUMNS = 3
_GRID_PADDING = 0.1          # meters between panels


class WindowAgent(BaseAgent):
    """Specialized agent for VR window lifecycle management.

    Args:
        registry:  The shared ``WindowRegistry`` instance.
        event_bus: The NEXUS OS ``EventBus`` for publishing commands.
    """

    def __init__(
        self,
        registry: WindowRegistry,
        event_bus: EventBus,
    ) -> None:
        super().__init__(
            name="window_agent",
            description=(
                "Manages VR spatial windows: create, close, move, resize, "
                "rotate, focus, and layout arrangement."
            ),
            capabilities=WINDOW_CAPABILITIES,
        )
        self._registry = registry
        self._event_bus = event_bus

        # Subscribe to Unity ack events for state reconciliation
        self._subscribe_to_events()

    # ── EventBus Subscriptions ──────────────────────────────────────────

    def _subscribe_to_events(self) -> None:
        """Listen for Unity acknowledgement events."""
        self._event_bus.subscribe("window.event.created", self._on_window_created)
        self._event_bus.subscribe("window.event.closed", self._on_window_closed)
        self._event_bus.subscribe("window.event.moved", self._on_window_moved)
        self._event_bus.subscribe("window.event.resized", self._on_window_resized)
        self._event_bus.subscribe("window.event.rotated", self._on_window_rotated)
        self._event_bus.subscribe("window.event.focused", self._on_window_focused)
        self._event_bus.subscribe("window.event.state_changed", self._on_state_changed)

    # ── Event Handlers (Unity → Python reconciliation) ──────────────────

    async def _on_window_created(self, data: dict[str, Any]) -> None:
        """Handle Unity's ack that a window was successfully created."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win and win.state == WindowState.CREATING:
            win.state = WindowState.OPEN
            logger.info("Window confirmed open: %s", wid)

    async def _on_window_closed(self, data: dict[str, Any]) -> None:
        """Handle Unity's ack that a window was destroyed."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win:
            win.state = WindowState.CLOSED
            self._registry.remove(wid)
            logger.info("Window confirmed closed: %s", wid)

    async def _on_window_moved(self, data: dict[str, Any]) -> None:
        """Reconcile position when user grabs a window in VR."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win:
            payload = data.get("payload", {})
            pos = payload.get("position", {})
            win.transform.position = Vec3(
                x=pos.get("x", win.transform.position.x),
                y=pos.get("y", win.transform.position.y),
                z=pos.get("z", win.transform.position.z),
            )

    async def _on_window_resized(self, data: dict[str, Any]) -> None:
        """Reconcile size after a resize event."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win:
            payload = data.get("payload", {})
            size = payload.get("size", {})
            win.size.width = size.get("width", win.size.width)
            win.size.height = size.get("height", win.size.height)

    async def _on_window_rotated(self, data: dict[str, Any]) -> None:
        """Reconcile rotation after a user-initiated rotation."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win:
            payload = data.get("payload", {})
            rot = payload.get("rotation", {})
            win.transform.rotation = Quat(
                x=rot.get("x", win.transform.rotation.x),
                y=rot.get("y", win.transform.rotation.y),
                z=rot.get("z", win.transform.rotation.z),
                w=rot.get("w", win.transform.rotation.w),
            )

    async def _on_window_focused(self, data: dict[str, Any]) -> None:
        """Handle Unity notifying us of a focus change (e.g. user clicked)."""
        wid = data.get("window_id", "")
        self._registry.set_focus(wid)

    async def _on_state_changed(self, data: dict[str, Any]) -> None:
        """Handle generic state change events from Unity."""
        wid = data.get("window_id", "")
        win = self._registry.get(wid)
        if win:
            payload = data.get("payload", {})
            new_state = payload.get("state", "")
            try:
                win.state = WindowState(new_state)
            except ValueError:
                logger.warning("Unknown state from Unity: %s", new_state)

    # ── Direct API ──────────────────────────────────────────────────────

    async def create_window(
        self,
        title: str,
        app_id: str = "",
        workspace_index: int = 0,
        position: Vec3 | None = None,
        size: WindowSize | None = None,
        anchor: WindowAnchor = WindowAnchor.WORLD_FIXED,
    ) -> VRWindow:
        """Create a new VR window and publish the command to Unity.

        If *position* is ``None``, an optimal spawn position is computed
        automatically based on existing windows in the workspace.

        Returns:
            The newly created ``VRWindow`` record (state=CREATING until ack'd).
        """
        # Auto-place if no position given
        if position is None:
            existing = self._registry.get_by_workspace(workspace_index)
            position = self._compute_spawn_position(existing)

        window = VRWindow(
            title=title,
            app_id=app_id,
            workspace_index=workspace_index,
            state=WindowState.CREATING,
            anchor=anchor,
            transform=WindowTransform(position=position),
            size=size or WindowSize(),
        )

        self._registry.add(window)
        self._registry.set_focus(window.window_id)

        # Build and publish create command
        payload = CreatePayload(
            title=title,
            app_id=app_id,
            workspace_index=workspace_index,
            transform=window.transform,
            size=window.size,
            anchor=anchor,
        )
        cmd = build_command(WindowCommandType.CREATE, window.window_id, payload)
        await self._publish_command(cmd)

        logger.info("Created window: %s (%s) at pos=(%.1f, %.1f, %.1f)",
                     window.window_id, title,
                     position.x, position.y, position.z)
        return window

    async def close_window(self, window_id: str) -> bool:
        """Request closure of a window.

        Sets the state to CLOSING; actual removal happens when Unity ack's.

        Returns:
            ``True`` if the window was found and close was requested.
        """
        win = self._registry.get(window_id)
        if win is None:
            logger.warning("Cannot close unknown window: %s", window_id)
            return False

        win.state = WindowState.CLOSING
        cmd = build_command(WindowCommandType.CLOSE, window_id)
        await self._publish_command(cmd)

        logger.info("Requested close: %s (%s)", window_id, win.title)
        return True

    async def move_window(
        self,
        window_id: str,
        position: Vec3,
        animate: bool = True,
    ) -> bool:
        """Move a window to a new 3D position.

        Returns:
            ``True`` if the window was found and the command was published.
        """
        win = self._registry.get(window_id)
        if win is None:
            return False

        win.transform.position = position
        payload = MovePayload(target_position=position, animate=animate)
        cmd = build_command(WindowCommandType.MOVE, window_id, payload)
        await self._publish_command(cmd)
        return True

    async def resize_window(
        self,
        window_id: str,
        size: WindowSize,
        animate: bool = True,
    ) -> bool:
        """Resize a window's spatial dimensions.

        Returns:
            ``True`` if the window was found and the command was published.
        """
        win = self._registry.get(window_id)
        if win is None:
            return False

        win.size = size
        payload = ResizePayload(target_size=size, animate=animate)
        cmd = build_command(WindowCommandType.RESIZE, window_id, payload)
        await self._publish_command(cmd)
        return True

    async def rotate_window(
        self,
        window_id: str,
        rotation: Quat,
        animate: bool = True,
    ) -> bool:
        """Rotate a window to a new orientation.

        Returns:
            ``True`` if the window was found and the command was published.
        """
        win = self._registry.get(window_id)
        if win is None:
            return False

        win.transform.rotation = rotation
        payload = RotatePayload(target_rotation=rotation, animate=animate)
        cmd = build_command(WindowCommandType.ROTATE, window_id, payload)
        await self._publish_command(cmd)
        return True

    async def focus_window(self, window_id: str) -> bool:
        """Bring a window to the foreground.

        Returns:
            ``True`` if the window was found and focus was set.
        """
        win = self._registry.set_focus(window_id)
        if win is None:
            return False

        payload = FocusPayload(focused=True)
        cmd = build_command(WindowCommandType.FOCUS, window_id, payload)
        await self._publish_command(cmd)
        return True

    async def set_window_state(
        self,
        window_id: str,
        state: WindowState,
    ) -> bool:
        """Set a window's lifecycle state (minimize, maximize, restore).

        Returns:
            ``True`` if the window was found and the command was published.
        """
        win = self._registry.get(window_id)
        if win is None:
            return False

        win.state = state
        payload = SetStatePayload(target_state=state)
        cmd = build_command(WindowCommandType.SET_STATE, window_id, payload)
        await self._publish_command(cmd)
        return True

    async def list_windows(
        self,
        workspace_index: int | None = None,
    ) -> list[VRWindow]:
        """Return active windows, optionally filtered by workspace."""
        if workspace_index is not None:
            return self._registry.get_by_workspace(workspace_index)
        return self._registry.get_all()

    async def arrange_layout(
        self,
        workspace_index: int,
        mode: str = "curved_arc",
    ) -> int:
        """Rearrange all windows in a workspace into a spatial layout.

        Args:
            workspace_index: Target workspace.
            mode: One of "curved_arc", "flat_grid", "free_floating".

        Returns:
            Number of windows rearranged.
        """
        windows = self._registry.get_by_workspace(workspace_index)
        open_windows = [
            w for w in windows
            if w.state in (WindowState.OPEN, WindowState.MAXIMIZED)
        ]

        if not open_windows:
            return 0

        if mode == "curved_arc":
            positions = self._layout_curved_arc(open_windows)
        elif mode == "flat_grid":
            positions = self._layout_flat_grid(open_windows)
        else:
            # free_floating — leave positions as-is
            return 0

        for win, (pos, rot) in zip(open_windows, positions):
            await self.move_window(win.window_id, pos, animate=True)
            await self.rotate_window(win.window_id, rot, animate=True)

        return len(open_windows)

    # ── Agent Execution Contract ────────────────────────────────────────

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Process a window management task.

        Supports two modes:
        1. **Direct execution**: If ``ctx.parameters`` contains a
           ``tool_name``, the corresponding tool is executed immediately.
        2. **Intent-based dispatch**: Keyword matching for create, close,
           move, resize, rotate, focus, list, and layout actions.
        """
        # Direct execution path
        tool_name = ctx.parameters.get("tool_name")
        if tool_name:
            return await self._execute_direct(tool_name, ctx.parameters.get("arguments", {}))

        # Intent-based dispatch (common patterns)
        intent = ctx.intent.lower().strip()
        params = ctx.parameters

        if any(kw in intent for kw in ("create", "open", "new window", "spawn")):
            pos = params.get("position")
            pos_vec = Vec3(**pos) if isinstance(pos, dict) else pos
            sz = params.get("size")
            sz_obj = WindowSize(**sz) if isinstance(sz, dict) else sz
            anchor = params.get("anchor", WindowAnchor.WORLD_FIXED)
            if isinstance(anchor, str):
                anchor = WindowAnchor(anchor)
            win = await self.create_window(
                title=params.get("title", "Untitled"),
                app_id=params.get("app_id", ""),
                workspace_index=params.get("workspace_index", 0),
                position=pos_vec,
                size=sz_obj,
                anchor=anchor,
            )
            return AgentResult(
                output=f"Created window '{win.title}' ({win.window_id})",
                data={"window_id": win.window_id, "title": win.title},
            )

        if any(kw in intent for kw in ("close", "destroy", "kill window")):
            wid = params.get("window_id", "")
            if not wid:
                return AgentResult(success=False, error="No window_id specified for close")
            ok = await self.close_window(wid)
            return AgentResult(
                success=ok,
                output=f"Close requested for {wid}" if ok else f"Window {wid} not found",
            )

        if any(kw in intent for kw in ("move", "reposition")):
            wid = params.get("window_id", "")
            pos = params.get("position", {})
            if not wid:
                return AgentResult(success=False, error="No window_id specified for move")
            ok = await self.move_window(
                wid,
                Vec3(x=pos.get("x", 0), y=pos.get("y", 1.5), z=pos.get("z", 2.5)),
            )
            return AgentResult(success=ok, output=f"Moved {wid}" if ok else f"Window {wid} not found")

        if any(kw in intent for kw in ("resize", "scale")):
            wid = params.get("window_id", "")
            size = params.get("size", {})
            if not wid:
                return AgentResult(success=False, error="No window_id specified for resize")
            ok = await self.resize_window(
                wid,
                WindowSize(width=size.get("width", 0.8), height=size.get("height", 0.5)),
            )
            return AgentResult(success=ok, output=f"Resized {wid}" if ok else f"Window {wid} not found")

        if any(kw in intent for kw in ("rotate", "turn", "tilt")):
            wid = params.get("window_id", "")
            rot = params.get("rotation", {})
            if not wid:
                return AgentResult(success=False, error="No window_id specified for rotate")
            ok = await self.rotate_window(
                wid,
                Quat(
                    x=rot.get("x", 0), y=rot.get("y", 0),
                    z=rot.get("z", 0), w=rot.get("w", 1),
                ),
            )
            return AgentResult(success=ok, output=f"Rotated {wid}" if ok else f"Window {wid} not found")

        if any(kw in intent for kw in ("focus", "select", "bring to front")):
            wid = params.get("window_id", "")
            if not wid:
                return AgentResult(success=False, error="No window_id specified for focus")
            ok = await self.focus_window(wid)
            return AgentResult(success=ok, output=f"Focused {wid}" if ok else f"Window {wid} not found")

        if any(kw in intent for kw in ("list", "show windows", "active windows")):
            workspace = params.get("workspace_index")
            windows = await self.list_windows(workspace)
            summaries = [
                f"  • {w.window_id}: {w.title} [{w.state.value}] "
                f"pos=({w.transform.position.x:.1f}, {w.transform.position.y:.1f}, {w.transform.position.z:.1f})"
                for w in windows
            ]
            return AgentResult(
                output=f"Active windows ({len(windows)}):\n" + "\n".join(summaries) if summaries else "No active windows.",
                data={"count": len(windows), "windows": [w.model_dump(mode="json") for w in windows]},
            )

        if any(kw in intent for kw in ("arrange", "layout", "tile", "organize")):
            mode = params.get("layout_mode", "curved_arc")
            workspace = params.get("workspace_index", 0)
            count = await self.arrange_layout(workspace, mode)
            return AgentResult(
                output=f"Arranged {count} window(s) in '{mode}' layout",
                data={"arranged_count": count, "mode": mode},
            )

        # Fallback: uninterpretable intent
        return AgentResult(
            success=False,
            error=f"Could not interpret window intent: {ctx.intent!r}",
        )

    # ── Private Helpers ─────────────────────────────────────────────────

    async def _execute_direct(self, tool_name: str, args: dict[str, Any]) -> AgentResult:
        """Execute a tool command directly without AI interpretation."""
        if tool_name in ("window_create", "create"):
            pos = args.get("position")
            pos_vec = Vec3(**pos) if isinstance(pos, dict) else pos
            sz = args.get("size")
            sz_obj = WindowSize(**sz) if isinstance(sz, dict) else sz
            anchor = args.get("anchor", WindowAnchor.WORLD_FIXED)
            if isinstance(anchor, str):
                anchor = WindowAnchor(anchor)
            win = await self.create_window(
                title=args.get("title", "Untitled"),
                app_id=args.get("app_id", ""),
                workspace_index=args.get("workspace_index", 0),
                position=pos_vec,
                size=sz_obj,
                anchor=anchor,
            )
            return AgentResult(
                output=f"Created window '{win.title}' ({win.window_id})",
                data={"window_id": win.window_id, "title": win.title},
            )

        if tool_name in ("window_close", "close"):
            wid = args.get("window_id", "")
            if not wid:
                return AgentResult(success=False, error="No window_id specified for close")
            ok = await self.close_window(wid)
            return AgentResult(
                success=ok,
                output=f"Close requested for {wid}" if ok else f"Window {wid} not found",
            )

        if tool_name in ("window_move", "move"):
            wid = args.get("window_id", "")
            pos = args.get("position", {})
            pos_vec = Vec3(**pos) if isinstance(pos, dict) else pos
            if not wid or not pos_vec:
                return AgentResult(success=False, error="window_id and position required for move")
            ok = await self.move_window(wid, pos_vec, animate=args.get("animate", True))
            return AgentResult(success=ok, output=f"Moved {wid}" if ok else f"Window {wid} not found")

        if tool_name in ("window_resize", "resize"):
            wid = args.get("window_id", "")
            size = args.get("size", {})
            size_obj = WindowSize(**size) if isinstance(size, dict) else size
            if not wid or not size_obj:
                return AgentResult(success=False, error="window_id and size required for resize")
            ok = await self.resize_window(wid, size_obj, animate=args.get("animate", True))
            return AgentResult(success=ok, output=f"Resized {wid}" if ok else f"Window {wid} not found")

        if tool_name in ("window_rotate", "rotate"):
            wid = args.get("window_id", "")
            rot = args.get("rotation", {})
            rot_obj = Quat(**rot) if isinstance(rot, dict) else rot
            if not wid or not rot_obj:
                return AgentResult(success=False, error="window_id and rotation required for rotate")
            ok = await self.rotate_window(wid, rot_obj, animate=args.get("animate", True))
            return AgentResult(success=ok, output=f"Rotated {wid}" if ok else f"Window {wid} not found")

        if tool_name in ("window_focus", "focus"):
            wid = args.get("window_id", "")
            if not wid:
                return AgentResult(success=False, error="No window_id specified for focus")
            ok = await self.focus_window(wid)
            return AgentResult(success=ok, output=f"Focused {wid}" if ok else f"Window {wid} not found")

        if tool_name in ("window_list", "list"):
            workspace = args.get("workspace_index")
            windows = await self.list_windows(workspace)
            return AgentResult(
                output=f"Active windows: {len(windows)}",
                data={"count": len(windows), "windows": [w.model_dump(mode="json") for w in windows]},
            )

        if tool_name in ("window_layout", "layout"):
            mode = args.get("layout_mode", "curved_arc")
            workspace = args.get("workspace_index", 0)
            count = await self.arrange_layout(workspace, mode)
            return AgentResult(
                output=f"Arranged {count} window(s) in '{mode}' layout",
                data={"arranged_count": count, "mode": mode},
            )

        return AgentResult(success=False, error=f"Unknown tool_name: {tool_name}")

    async def _publish_command(self, cmd: WindowCommand) -> None:
        """Serialize a WindowCommand and publish it to the EventBus."""
        suffix = cmd.type.value.split(".")[-1]
        topic = f"window.command.{suffix}"
        await self._event_bus.publish(topic, cmd.model_dump(mode="json"))

    # ── Spatial Layout Algorithms ───────────────────────────────────────

    def _compute_spawn_position(self, existing_windows: list[VRWindow]) -> Vec3:
        """Compute an optimal spawn position for a new window.

        Strategy:
          1. If no existing windows, place at center front.
          2. Otherwise, find the largest angular gap between existing
             windows on the cylindrical arc and place the new window
             in the middle of that gap.
        """
        if not existing_windows:
            return Vec3(x=0.0, y=_DEFAULT_HEIGHT, z=_DEFAULT_RADIUS)

        # Compute angles of existing windows (atan2 from center)
        angles: list[float] = []
        for w in existing_windows:
            px = w.transform.position.x
            pz = w.transform.position.z
            angle = math.degrees(math.atan2(px, pz))
            angles.append(angle)

        angles.sort()

        # Find the largest gap
        max_gap = 0.0
        best_angle = 0.0

        for i in range(len(angles)):
            next_i = (i + 1) % len(angles)
            gap = angles[next_i] - angles[i]
            if next_i == 0:
                gap += 360.0
            if gap > max_gap:
                max_gap = gap
                best_angle = angles[i] + gap / 2.0

        # Clamp to comfort arc
        best_angle = max(-_ARC_HALF_ANGLE, min(_ARC_HALF_ANGLE, best_angle))

        rad = math.radians(best_angle)
        return Vec3(
            x=_DEFAULT_RADIUS * math.sin(rad),
            y=_DEFAULT_HEIGHT,
            z=_DEFAULT_RADIUS * math.cos(rad),
        )

    def _layout_curved_arc(
        self, windows: list[VRWindow],
    ) -> list[tuple[Vec3, Quat]]:
        """Compute positions along a curved arc for the given windows."""
        n = len(windows)
        if n == 0:
            return []

        if n == 1:
            return [(
                Vec3(x=0.0, y=_DEFAULT_HEIGHT, z=_DEFAULT_RADIUS),
                Quat.identity(),
            )]

        results: list[tuple[Vec3, Quat]] = []
        total_angle = min(2 * _ARC_HALF_ANGLE, n * 20.0)  # adaptive spread
        start_angle = -total_angle / 2.0
        step = total_angle / (n - 1) if n > 1 else 0.0

        for i in range(n):
            angle_deg = start_angle + i * step
            angle_rad = math.radians(angle_deg)

            pos = Vec3(
                x=_DEFAULT_RADIUS * math.sin(angle_rad),
                y=_DEFAULT_HEIGHT,
                z=_DEFAULT_RADIUS * math.cos(angle_rad),
            )
            rot = Quat.from_euler_y(angle_deg)
            results.append((pos, rot))

        return results

    def _layout_flat_grid(
        self, windows: list[VRWindow],
    ) -> list[tuple[Vec3, Quat]]:
        """Compute positions in a flat grid arrangement."""
        n = len(windows)
        if n == 0:
            return []

        cols = min(n, _GRID_COLUMNS)
        rows = math.ceil(n / cols)

        # Compute total grid dimensions
        avg_width = sum(w.size.width for w in windows) / n
        avg_height = sum(w.size.height for w in windows) / n
        cell_w = avg_width + _GRID_PADDING
        cell_h = avg_height + _GRID_PADDING
        total_w = cols * cell_w
        total_h = rows * cell_h

        results: list[tuple[Vec3, Quat]] = []
        identity = Quat.identity()

        for i in range(n):
            row = i // cols
            col = i % cols

            x = (col * cell_w) - (total_w / 2.0) + (cell_w / 2.0)
            y = _DEFAULT_HEIGHT + ((rows - 1 - row) * cell_h) - (total_h / 2.0) + (cell_h / 2.0)

            pos = Vec3(x=x, y=y, z=_DEFAULT_RADIUS)
            results.append((pos, identity))

        return results
