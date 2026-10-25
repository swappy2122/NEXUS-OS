"""Window agent for NEXUS OS.

Manages the lifecycle of VR windows: creating, closing, moving,
resizing, rotating, focusing, and snapping windows to layouts.

Responsibilities:
    1. Process natural-language or structured intents about windows.
    2. Maintain authoritative window state in ``WindowStateStore``.
    3. Emit ``WindowCommand`` messages toward Unity via ``VRBridgeClient``.
    4. Handle ``WindowEvent`` callbacks from Unity to reconcile state.

The WindowAgent is intentionally *separate* from the AppAgent:
    - An application can exist without a window (headless process).
    - A window can exist without an application (pinned note, clock).
    - Their lifecycles are independent.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, Capability
from agents.vr_bridge import IVRBridge
from agents.window_layout import IWindowLayoutEngine, WindowLayoutEngine
from agents.window_state_store import IWindowStateStore, WindowStateStore
from core.vr_types import (
    Quaternion3D,
    Vector3D,
    WindowCommand,
    WindowCommandType,
    WindowContentType,
    WindowEvent,
    WindowEventType,
    WindowLayoutMode,
    WindowSize,
    WindowState,
)

logger = logging.getLogger("nexus.agent.window")

# ---------------------------------------------------------------------------
# Capability declarations
# ---------------------------------------------------------------------------

WINDOW_CAPABILITIES = [
    Capability(name="window_create", description="Create a new VR window"),
    Capability(name="window_close", description="Close / destroy a VR window"),
    Capability(name="window_move", description="Move a window to a 3D position"),
    Capability(name="window_resize", description="Resize a window"),
    Capability(name="window_rotate", description="Rotate a window in 3D"),
    Capability(name="window_focus", description="Focus / select a window"),
    Capability(name="window_list", description="List all open windows"),
    Capability(name="window_snap", description="Snap windows to a spatial layout"),
]


# ---------------------------------------------------------------------------
# Agent implementation (Deterministic, Non-AI)
# ---------------------------------------------------------------------------

class WindowAgent(BaseAgent):
    """Specialized agent for VR window lifecycle management (Deterministic, Non-AI)."""

    def __init__(
        self,
        state_store: IWindowStateStore | None = None,
        bridge: IVRBridge | None = None,
        layout_engine: IWindowLayoutEngine | None = None,
    ) -> None:
        super().__init__(
            name="window_agent",
            description=(
                "Manages VR windows: create, close, move, resize, rotate, "
                "focus, and spatial layout snapping."
            ),
            capabilities=WINDOW_CAPABILITIES,
        )
        self._store: IWindowStateStore = state_store or WindowStateStore()
        self._bridge: IVRBridge | None = bridge
        self._layout: IWindowLayoutEngine = layout_engine or WindowLayoutEngine()

    @property
    def store(self) -> IWindowStateStore:
        """Return the window state store."""
        return self._store

    @property
    def bridge(self) -> IVRBridge | None:
        """Return the attached VR bridge, if any."""
        return self._bridge

    @property
    def layout_engine(self) -> IWindowLayoutEngine:
        """Return the layout engine."""
        return self._layout

    # ── bridge wiring ────────────────────────────────────────────────────

    def set_bridge(self, bridge: IVRBridge) -> None:
        """Inject the VR bridge and register our event handler."""
        self._bridge = bridge
        bridge.on_event(self._handle_vr_event)
        logger.info("VR bridge attached to WindowAgent")

    # ── agent execution contract ─────────────────────────────────────────

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Process a window management task deterministically without AI.

        Execution paths:
        1. **Direct action**: ``ctx.parameters`` contains an ``action``.
        2. **Tool execution**: ``ctx.parameters`` contains a ``tool_name``.
        3. **Rule-based intent parsing**: Deterministically extracts action
           from natural language intent without an LLM.
        """
        # 1. Direct action path
        action = ctx.parameters.get("action")
        if action:
            return await self._direct_execute(action, ctx.parameters)

        # 2. Tool name execution path
        tool_name = ctx.parameters.get("tool_name")
        if tool_name:
            args = ctx.parameters.get("arguments", {})
            if tool_name in self._tools:
                tool_res = await self.use_tool(tool_name, **args)
                return AgentResult(
                    success=tool_res.success,
                    output=str(tool_res.output) if tool_res.success else "",
                    error=tool_res.error,
                    data={"tool_name": tool_name},
                )
            if tool_name.startswith("window_"):
                action_name = tool_name[len("window_"):]
                return await self._direct_execute(action_name, args)

        # 3. Deterministic rule-based intent parsing (No AI)
        action, params = self._parse_intent_deterministically(ctx.intent)
        if action:
            # Merge any explicit parameters with parsed parameters
            merged_params = {**params, **ctx.parameters}
            return await self._direct_execute(action, merged_params)

        return AgentResult(
            success=False,
            error=f"Could not parse window action from intent: '{ctx.intent}'",
        )

    def _parse_intent_deterministically(self, intent: str) -> tuple[str | None, dict[str, Any]]:
        """Extract window action and parameters using deterministic rules."""
        lower = intent.lower().strip()

        # List windows
        if any(kw in lower for kw in ["list window", "list open", "show window", "get window", "all window"]):
            return "list", {}

        # Close window
        if any(kw in lower for kw in ["close window", "destroy window", "remove window", "kill window", "close "]):
            # Try to extract title/name after 'close' or 'window'
            words = lower.split()
            target = None
            if "window" in words:
                idx = words.index("window")
                if idx + 1 < len(words):
                    target = " ".join(words[idx + 1:])
            elif words and words[0] == "close" and len(words) > 1:
                target = " ".join(words[1:])
            params = {"title": target} if target else {}
            return "close", params

        # Create window
        if any(kw in lower for kw in ["create window", "new window", "open window", "add window", "make window"]):
            words = lower.split()
            target = "New Window"
            if "window" in words:
                idx = words.index("window")
                if idx + 1 < len(words):
                    target = " ".join(words[idx + 1:]).strip("'\"")
            return "create", {"title": target}

        # Focus / select window
        if any(kw in lower for kw in ["focus window", "select window", "focus", "select"]):
            words = lower.split()
            target = None
            if "window" in words:
                idx = words.index("window")
                if idx + 1 < len(words):
                    target = " ".join(words[idx + 1:])
            elif words and words[0] in ("focus", "select") and len(words) > 1:
                target = " ".join(words[1:])
            params = {"title": target} if target else {}
            return "focus", params

        # Snap / layout
        if any(kw in lower for kw in ["snap", "tile", "arrange", "layout"]):
            layout = "curved_arc"
            if "grid" in lower:
                layout = "flat_grid"
            elif "float" in lower:
                layout = "free_floating"
            return "snap", {"layout": layout}

        # Move window
        if "move" in lower:
            return "move", {}

        # Resize window
        if "resize" in lower:
            return "resize", {}

        # Rotate window
        if "rotate" in lower or "turn" in lower:
            return "rotate", {}

        return None, {}

    # ── direct action dispatch ───────────────────────────────────────────

    async def _direct_execute(
        self, action: str, params: dict[str, Any],
    ) -> AgentResult:
        """Route a structured action to the appropriate handler."""
        handlers = {
            "create": self._action_create,
            "close": self._action_close,
            "move": self._action_move,
            "resize": self._action_resize,
            "rotate": self._action_rotate,
            "focus": self._action_focus,
            "list": self._action_list,
            "snap": self._action_snap,
        }

        handler = handlers.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                error=f"Unknown window action: '{action}'",
            )

        try:
            return await handler(params)
        except Exception as exc:
            logger.exception("Window action '%s' failed", action)
            return AgentResult(success=False, error=str(exc))

    # ── action handlers ──────────────────────────────────────────────────

    async def _action_create(self, params: dict[str, Any]) -> AgentResult:
        """Create a new VR window."""
        state = WindowState(
            title=params.get("title", "New Window"),
            app_id=params.get("app_id"),
            workspace_id=params.get("workspace_id", "workspace_1"),
            position=Vector3D(**params["position"]) if "position" in params else Vector3D(x=0.0, y=1.5, z=2.5),
            rotation=Quaternion3D(**params["rotation"]) if "rotation" in params else Quaternion3D.identity(),
            size=WindowSize(**params["size"]) if "size" in params else WindowSize(),
            content_type=WindowContentType(params.get("content_type", "custom")),
            metadata=params.get("metadata", {}),
        )

        created = self._store.create(state)
        self._store.set_focus(created.window_id)

        # Send CREATE command to Unity
        await self._send_command(WindowCommand(
            command_type=WindowCommandType.CREATE,
            window_id=created.window_id,
            payload=created.model_dump(mode="json"),
        ))

        return AgentResult(
            output=f"Created window '{created.title}' (id={created.window_id})",
            data={"window_id": created.window_id, "action": "create"},
        )

    async def _action_close(self, params: dict[str, Any]) -> AgentResult:
        """Close an existing VR window."""
        window_id = self._resolve_window_id(params)
        if window_id is None:
            return AgentResult(success=False, error="Could not resolve window to close")

        window = self._store.get(window_id)
        if window is None:
            return AgentResult(success=False, error=f"Window '{window_id}' not found")

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.CLOSE,
            window_id=window_id,
        ))

        title = window.title
        self._store.remove(window_id)

        return AgentResult(
            output=f"Closed window '{title}' (id={window_id})",
            data={"window_id": window_id, "action": "close"},
        )

    async def _action_move(self, params: dict[str, Any]) -> AgentResult:
        """Move a window to a new position."""
        window_id = self._resolve_window_id(params)
        if window_id is None:
            return AgentResult(success=False, error="Could not resolve window to move")

        position = Vector3D(**params["position"]) if "position" in params else None
        if position is None:
            return AgentResult(success=False, error="No position specified for move")

        self._store.update(window_id, position=position)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.MOVE,
            window_id=window_id,
            payload={
                "position": position.model_dump(),
                "animate": params.get("animate", True),
            },
        ))

        return AgentResult(
            output=f"Moved window '{window_id}' to {position}",
            data={"window_id": window_id, "action": "move"},
        )

    async def _action_resize(self, params: dict[str, Any]) -> AgentResult:
        """Resize a window."""
        window_id = self._resolve_window_id(params)
        if window_id is None:
            return AgentResult(success=False, error="Could not resolve window to resize")

        size = WindowSize(**params["size"]) if "size" in params else None
        if size is None:
            return AgentResult(success=False, error="No size specified for resize")

        self._store.update(window_id, size=size)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.RESIZE,
            window_id=window_id,
            payload={
                "size": size.model_dump(),
                "anchor": params.get("anchor", "center"),
            },
        ))

        return AgentResult(
            output=f"Resized window '{window_id}' to {size}",
            data={"window_id": window_id, "action": "resize"},
        )

    async def _action_rotate(self, params: dict[str, Any]) -> AgentResult:
        """Rotate a window."""
        window_id = self._resolve_window_id(params)
        if window_id is None:
            return AgentResult(success=False, error="Could not resolve window to rotate")

        rotation = Quaternion3D(**params["rotation"]) if "rotation" in params else None
        if rotation is None:
            return AgentResult(success=False, error="No rotation specified")

        self._store.update(window_id, rotation=rotation)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.ROTATE,
            window_id=window_id,
            payload={
                "rotation": rotation.model_dump(),
                "animate": params.get("animate", True),
            },
        ))

        return AgentResult(
            output=f"Rotated window '{window_id}'",
            data={"window_id": window_id, "action": "rotate"},
        )

    async def _action_focus(self, params: dict[str, Any]) -> AgentResult:
        """Focus / select a window."""
        window_id = self._resolve_window_id(params)
        if window_id is None:
            return AgentResult(success=False, error="Could not resolve window to focus")

        self._store.set_focus(window_id)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.FOCUS,
            window_id=window_id,
        ))

        return AgentResult(
            output=f"Focused window '{window_id}'",
            data={"window_id": window_id, "action": "focus"},
        )

    async def _action_list(self, params: dict[str, Any]) -> AgentResult:
        """List all open windows."""
        workspace_id = params.get("workspace_id")

        if workspace_id:
            windows = self._store.get_by_workspace(workspace_id)
        else:
            windows = self._store.list_all()

        if not windows:
            return AgentResult(output="No windows open.")

        lines = []
        for w in windows:
            focus_marker = " ★" if w.is_focused else ""
            pin_marker = " 📌" if w.is_pinned else ""
            lines.append(
                f"  [{w.window_id}] {w.title} "
                f"({w.content_type.value}){focus_marker}{pin_marker}"
            )

        return AgentResult(
            output=f"Open windows ({len(windows)}):\n" + "\n".join(lines),
            data={"window_count": len(windows), "action": "list"},
        )

    async def _action_snap(self, params: dict[str, Any]) -> AgentResult:
        """Snap all windows in the current workspace to a layout."""
        layout_str = params.get("layout", "curved_arc")
        layout = WindowLayoutMode(layout_str)
        workspace_id = params.get("workspace_id", "workspace_1")

        windows = self._store.get_by_workspace(workspace_id)
        if not windows:
            return AgentResult(output="No windows to snap.")

        user_pos = Vector3D(**params["user_position"]) if "user_position" in params else Vector3D.zero()
        user_fwd = Vector3D(**params["user_forward"]) if "user_forward" in params else Vector3D.forward()

        positions = self._layout.compute_positions(windows, layout, user_pos, user_fwd)

        # Issue MOVE commands for each window
        for window_id, position in positions.items():
            self._store.update(window_id, position=position)
            await self._send_command(WindowCommand(
                command_type=WindowCommandType.MOVE,
                window_id=window_id,
                payload={
                    "position": position.model_dump(),
                    "animate": True,
                },
            ))

        return AgentResult(
            output=f"Snapped {len(positions)} windows to {layout.value} layout",
            data={"layout": layout.value, "window_count": len(positions), "action": "snap"},
        )

    # ── VR event handling ────────────────────────────────────────────────

    async def _handle_vr_event(self, event: WindowEvent) -> None:
        """Process incoming events from the Unity VR shell."""
        handler_map = {
            WindowEventType.POSITION_CHANGED: self._on_position_changed,
            WindowEventType.ROTATION_CHANGED: self._on_rotation_changed,
            WindowEventType.SIZE_CHANGED: self._on_size_changed,
            WindowEventType.INTERACTION_FOCUS_REQUEST: self._on_focus_request,
            WindowEventType.INTERACTION_CLOSE_REQUEST: self._on_close_request,
            WindowEventType.WINDOW_CREATED_ACK: self._on_created_ack,
            WindowEventType.WINDOW_CLOSED_ACK: self._on_closed_ack,
        }

        handler = handler_map.get(event.event_type)
        if handler:
            await handler(event)
        else:
            logger.debug(
                "Unhandled VR event type: %s (window=%s)",
                event.event_type.value, event.window_id,
            )

    async def _on_position_changed(self, event: WindowEvent) -> None:
        """User physically moved a window in VR — reconcile state."""
        pos_data = event.payload.get("position", {})
        if pos_data:
            position = Vector3D(**pos_data)
            try:
                self._store.update(event.window_id, position=position)
            except KeyError:
                logger.warning("Position changed for unknown window '%s'", event.window_id)

    async def _on_rotation_changed(self, event: WindowEvent) -> None:
        """User rotated a window in VR — reconcile state."""
        rot_data = event.payload.get("rotation", {})
        if rot_data:
            rotation = Quaternion3D(**rot_data)
            try:
                self._store.update(event.window_id, rotation=rotation)
            except KeyError:
                logger.warning("Rotation changed for unknown window '%s'", event.window_id)

    async def _on_size_changed(self, event: WindowEvent) -> None:
        """User resized a window in VR — reconcile state."""
        size_data = event.payload.get("size", {})
        if size_data:
            size = WindowSize(**size_data)
            try:
                self._store.update(event.window_id, size=size)
            except KeyError:
                logger.warning("Size changed for unknown window '%s'", event.window_id)

    async def _on_focus_request(self, event: WindowEvent) -> None:
        """User clicked / gazed at a window — set focus."""
        try:
            self._store.set_focus(event.window_id)
        except KeyError:
            logger.warning("Focus request for unknown window '%s'", event.window_id)

    async def _on_close_request(self, event: WindowEvent) -> None:
        """User closed a window via VR interaction — remove from store."""
        self._store.remove(event.window_id)

    async def _on_created_ack(self, event: WindowEvent) -> None:
        """Unity confirmed window creation."""
        logger.info("Unity acknowledged creation of window '%s'", event.window_id)

    async def _on_closed_ack(self, event: WindowEvent) -> None:
        """Unity confirmed window destruction."""
        self._store.remove(event.window_id)
        logger.info("Unity acknowledged closure of window '%s'", event.window_id)

    # ── helpers ──────────────────────────────────────────────────────────

    def _resolve_window_id(self, params: dict[str, Any]) -> str | None:
        """Resolve a window from params — by ID, title, or app_id."""
        # Direct ID
        window_id = params.get("window_id")
        if window_id and self._store.get(window_id):
            return window_id

        # By title (fuzzy match)
        title = params.get("title")
        if title:
            for w in self._store.list_all():
                if title.lower() in w.title.lower():
                    return w.window_id

        # By app_id
        app_id = params.get("app_id")
        if app_id:
            windows = self._store.get_by_app(app_id)
            if windows:
                return windows[0].window_id

        # Fallback: currently focused window
        focused = self._store.get_focused()
        if focused:
            return focused.window_id

        return None

    async def _send_command(self, command: WindowCommand) -> None:
        """Send a command to Unity via the bridge, if connected."""
        if self._bridge is None:
            logger.debug(
                "No VR bridge — command %s for window '%s' not sent",
                command.command_type.value, command.window_id,
            )
            return

        await self._bridge.send_command(command)

    # ── introspection ────────────────────────────────────────────────────

    def get_store_snapshot(self) -> dict[str, Any]:
        """Return a diagnostic snapshot of the window state store."""
        return self._store.describe()

    # ── programmatic API (Deterministic, Non-AI) ─────────────────────────

    async def create_window(
        self,
        title: str = "New Window",
        app_id: str | None = None,
        workspace_id: str = "workspace_1",
        position: Vector3D | dict[str, float] | None = None,
        rotation: Quaternion3D | dict[str, float] | None = None,
        size: WindowSize | dict[str, float] | None = None,
        content_type: WindowContentType | str = WindowContentType.CUSTOM,
        metadata: dict[str, Any] | None = None,
    ) -> WindowState:
        """Programmatically create a new VR window and notify Unity."""
        if isinstance(position, dict):
            pos = Vector3D(**position)
        elif position is None:
            pos = Vector3D(x=0.0, y=1.5, z=2.5)
        else:
            pos = position

        if isinstance(rotation, dict):
            rot = Quaternion3D(**rotation)
        elif rotation is None:
            rot = Quaternion3D.identity()
        else:
            rot = rotation

        if isinstance(size, dict):
            sz = WindowSize(**size)
        elif size is None:
            sz = WindowSize()
        else:
            sz = size

        if isinstance(content_type, str):
            c_type = WindowContentType(content_type)
        else:
            c_type = content_type

        state = WindowState(
            title=title,
            app_id=app_id,
            workspace_id=workspace_id,
            position=pos,
            rotation=rot,
            size=sz,
            content_type=c_type,
            metadata=metadata or {},
        )
        created = self._store.create(state)
        self._store.set_focus(created.window_id)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.CREATE,
            window_id=created.window_id,
            payload=created.model_dump(mode="json"),
        ))
        return created

    async def close_window(
        self,
        window_id: str | None = None,
        title: str | None = None,
        app_id: str | None = None,
    ) -> bool:
        """Programmatically close an existing VR window."""
        target_id = self._resolve_window_id({
            "window_id": window_id,
            "title": title,
            "app_id": app_id,
        })
        if not target_id or not self._store.get(target_id):
            return False

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.CLOSE,
            window_id=target_id,
        ))
        return self._store.remove(target_id)

    async def move_window(
        self,
        position: Vector3D | dict[str, float],
        window_id: str | None = None,
        title: str | None = None,
        animate: bool = True,
    ) -> WindowState:
        """Programmatically move a window to a new 3D position."""
        target_id = self._resolve_window_id({
            "window_id": window_id,
            "title": title,
        })
        if not target_id:
            raise ValueError(f"Could not resolve window to move (id={window_id}, title={title})")

        pos = Vector3D(**position) if isinstance(position, dict) else position
        updated = self._store.update(target_id, position=pos)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.MOVE,
            window_id=target_id,
            payload={"position": pos.model_dump(), "animate": animate},
        ))
        return updated

    async def resize_window(
        self,
        size: WindowSize | dict[str, float],
        window_id: str | None = None,
        title: str | None = None,
        anchor: str = "center",
    ) -> WindowState:
        """Programmatically resize a window."""
        target_id = self._resolve_window_id({
            "window_id": window_id,
            "title": title,
        })
        if not target_id:
            raise ValueError(f"Could not resolve window to resize (id={window_id}, title={title})")

        sz = WindowSize(**size) if isinstance(size, dict) else size
        updated = self._store.update(target_id, size=sz)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.RESIZE,
            window_id=target_id,
            payload={"size": sz.model_dump(), "anchor": anchor},
        ))
        return updated

    async def rotate_window(
        self,
        rotation: Quaternion3D | dict[str, float],
        window_id: str | None = None,
        title: str | None = None,
        animate: bool = True,
    ) -> WindowState:
        """Programmatically rotate a window."""
        target_id = self._resolve_window_id({
            "window_id": window_id,
            "title": title,
        })
        if not target_id:
            raise ValueError(f"Could not resolve window to rotate (id={window_id}, title={title})")

        rot = Quaternion3D(**rotation) if isinstance(rotation, dict) else rotation
        updated = self._store.update(target_id, rotation=rot)

        await self._send_command(WindowCommand(
            command_type=WindowCommandType.ROTATE,
            window_id=target_id,
            payload={"rotation": rot.model_dump(), "animate": animate},
        ))
        return updated

    async def focus_window(
        self,
        window_id: str | None = None,
        title: str | None = None,
    ) -> WindowState:
        """Programmatically focus a window."""
        target_id = self._resolve_window_id({
            "window_id": window_id,
            "title": title,
        })
        if not target_id:
            raise ValueError(f"Could not resolve window to focus (id={window_id}, title={title})")

        self._store.set_focus(target_id)
        await self._send_command(WindowCommand(
            command_type=WindowCommandType.FOCUS,
            window_id=target_id,
        ))
        window = self._store.get(target_id)
        if window is None:
            raise KeyError(f"Window '{target_id}' not found after focus")
        return window

    def list_windows(self, workspace_id: str | None = None) -> list[WindowState]:
        """Return all open windows (optionally filtered by workspace)."""
        if workspace_id:
            return self._store.get_by_workspace(workspace_id)
        return self._store.list_all()

    def get_window(self, window_id: str) -> WindowState | None:
        """Get a single window by ID."""
        return self._store.get(window_id)

    async def snap_to_layout(
        self,
        layout: WindowLayoutMode | str = WindowLayoutMode.CURVED_ARC,
        workspace_id: str = "workspace_1",
        user_position: Vector3D | None = None,
        user_forward: Vector3D | None = None,
    ) -> dict[str, Vector3D]:
        """Snap all windows in a workspace to a spatial layout."""
        mode = WindowLayoutMode(layout) if isinstance(layout, str) else layout
        windows = self._store.get_by_workspace(workspace_id)
        if not windows:
            return {}

        u_pos = user_position or Vector3D.zero()
        u_fwd = user_forward or Vector3D.forward()
        positions = self._layout.compute_positions(windows, mode, u_pos, u_fwd)

        for w_id, pos in positions.items():
            self._store.update(w_id, position=pos)
            await self._send_command(WindowCommand(
                command_type=WindowCommandType.MOVE,
                window_id=w_id,
                payload={"position": pos.model_dump(), "animate": True},
            ))

        return positions
