"""VR Window management tools for NEXUS OS.

Provides safe, permission-gated tools for spatial VR window operations:
- Creating spatial windows with position, size, and content type
- Moving windows in 3D space
- Resizing windows (width and height in meters)
- Rotating windows via 3D quaternions
- Focusing / selecting windows
- Closing windows
- Listing open windows
- Snapping windows to ergonomic spatial layouts
"""

from __future__ import annotations

import logging
from typing import Any

from core.types import ToolResult
from core.vr_types import (
    Quaternion3D,
    Vector3D,
    WindowContentType,
    WindowLayoutMode,
    WindowSize,
    WindowState,
)
from security.models import ActionCategory, RiskLevel
from tools.base import BaseTool

logger = logging.getLogger("nexus.tools.window")

# Module-level default agent instance
_default_window_agent: Any = None


def get_default_window_agent() -> Any:
    """Return the global default WindowAgent instance."""
    global _default_window_agent
    if _default_window_agent is None:
        from agents.window_agent import WindowAgent
        _default_window_agent = WindowAgent()
    return _default_window_agent


def set_default_window_agent(agent: Any) -> None:
    """Set the global default WindowAgent instance."""
    global _default_window_agent
    _default_window_agent = agent


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

class WindowCreateTool(BaseTool):
    """Create a new spatial VR window."""

    name = "window_create"
    description = (
        "Create a new spatial VR window in the user's workspace with "
        "specified title, position, rotation, size, and content type."
    )
    required_permissions = ["window.create"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Title of the window.",
                "default": "New Window",
            },
            "app_id": {
                "type": "string",
                "description": "Optional associated application ID.",
            },
            "workspace_id": {
                "type": "string",
                "description": "Workspace ID where the window belongs.",
                "default": "workspace_1",
            },
            "position": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "description": "3D position coordinates (meters). Defaults to (0.0, 1.5, 2.5).",
            },
            "rotation": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                    "w": {"type": "number"},
                },
                "description": "Quaternion rotation (x, y, z, w). Defaults to identity.",
            },
            "size": {
                "type": "object",
                "properties": {
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
                "description": "Window dimensions in meters. Defaults to 1.2 x 0.8.",
            },
            "content_type": {
                "type": "string",
                "description": "Type of content (terminal, web_browser, file_browser, text_editor, system_monitor, media_player, ai_chat, custom).",
                "default": "custom",
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary metadata for the window.",
            },
        },
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            agent = self._get_agent()
            state = await agent.create_window(
                title=kwargs.get("title", "New Window"),
                app_id=kwargs.get("app_id"),
                workspace_id=kwargs.get("workspace_id", "workspace_1"),
                position=kwargs.get("position"),
                rotation=kwargs.get("rotation"),
                size=kwargs.get("size"),
                content_type=kwargs.get("content_type", "custom"),
                metadata=kwargs.get("metadata"),
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=state.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.exception("WindowCreateTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to create window: {exc}",
            )


class WindowCloseTool(BaseTool):
    """Close an existing VR window."""

    name = "window_close"
    description = "Close / destroy an existing VR window by window_id or title."
    required_permissions = ["window.close"]
    action_category = ActionCategory.SENSITIVE
    risk_level = RiskLevel.MEDIUM
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_id": {
                "type": "string",
                "description": "ID of the window to close.",
            },
            "title": {
                "type": "string",
                "description": "Title or substring of the window to close.",
            },
            "app_id": {
                "type": "string",
                "description": "Associated app_id of the window to close.",
            },
        },
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            agent = self._get_agent()
            closed = await agent.close_window(
                window_id=kwargs.get("window_id"),
                title=kwargs.get("title"),
                app_id=kwargs.get("app_id"),
            )
            if closed:
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"closed": True, "target": kwargs.get("window_id") or kwargs.get("title") or kwargs.get("app_id")},
                )
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Window not found or could not be closed with params: {kwargs}",
            )
        except Exception as exc:
            logger.exception("WindowCloseTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to close window: {exc}",
            )


class WindowMoveTool(BaseTool):
    """Move a VR window to a new 3D position."""

    name = "window_move"
    description = "Move a VR window to target 3D coordinates (x, y, z in meters)."
    required_permissions = ["window.move"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_id": {
                "type": "string",
                "description": "ID of the window to move (optional if title is given or focused window is targeted).",
            },
            "title": {
                "type": "string",
                "description": "Title of the window to move.",
            },
            "position": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y", "z"],
                "description": "New 3D position coordinates (meters).",
            },
            "animate": {
                "type": "boolean",
                "description": "Whether to smoothly animate the movement.",
                "default": True,
            },
        },
        "required": ["position"],
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            position = kwargs.get("position")
            if not position:
                return ToolResult(tool_name=self.name, success=False, error="Position parameter is required")

            agent = self._get_agent()
            updated = await agent.move_window(
                position=position,
                window_id=kwargs.get("window_id"),
                title=kwargs.get("title"),
                animate=kwargs.get("animate", True),
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=updated.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.exception("WindowMoveTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to move window: {exc}",
            )


class WindowResizeTool(BaseTool):
    """Resize a VR window."""

    name = "window_resize"
    description = "Resize a VR window to a new width and height in meters."
    required_permissions = ["window.resize"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_id": {
                "type": "string",
                "description": "ID of the window to resize.",
            },
            "title": {
                "type": "string",
                "description": "Title of the window to resize.",
            },
            "size": {
                "type": "object",
                "properties": {
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
                "required": ["width", "height"],
                "description": "New dimensions (width and height in meters).",
            },
            "anchor": {
                "type": "string",
                "description": "Resize anchor point (e.g. center, top-left).",
                "default": "center",
            },
        },
        "required": ["size"],
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            size = kwargs.get("size")
            if not size:
                return ToolResult(tool_name=self.name, success=False, error="Size parameter is required")

            agent = self._get_agent()
            updated = await agent.resize_window(
                size=size,
                window_id=kwargs.get("window_id"),
                title=kwargs.get("title"),
                anchor=kwargs.get("anchor", "center"),
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=updated.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.exception("WindowResizeTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to resize window: {exc}",
            )


class WindowRotateTool(BaseTool):
    """Rotate a VR window in 3D space."""

    name = "window_rotate"
    description = "Rotate a VR window in 3D space using a quaternion (x, y, z, w)."
    required_permissions = ["window.rotate"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_id": {
                "type": "string",
                "description": "ID of the window to rotate.",
            },
            "title": {
                "type": "string",
                "description": "Title of the window to rotate.",
            },
            "rotation": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                    "w": {"type": "number"},
                },
                "required": ["x", "y", "z", "w"],
                "description": "Quaternion rotation coordinates.",
            },
            "animate": {
                "type": "boolean",
                "description": "Whether to smoothly animate the rotation.",
                "default": True,
            },
        },
        "required": ["rotation"],
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            rotation = kwargs.get("rotation")
            if not rotation:
                return ToolResult(tool_name=self.name, success=False, error="Rotation parameter is required")

            agent = self._get_agent()
            updated = await agent.rotate_window(
                rotation=rotation,
                window_id=kwargs.get("window_id"),
                title=kwargs.get("title"),
                animate=kwargs.get("animate", True),
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=updated.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.exception("WindowRotateTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to rotate window: {exc}",
            )


class WindowFocusTool(BaseTool):
    """Focus / select a VR window."""

    name = "window_focus"
    description = "Focus / select a VR window (bring it forward in z-order)."
    required_permissions = ["window.focus"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "window_id": {
                "type": "string",
                "description": "ID of the window to focus.",
            },
            "title": {
                "type": "string",
                "description": "Title of the window to focus.",
            },
        },
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            agent = self._get_agent()
            focused = await agent.focus_window(
                window_id=kwargs.get("window_id"),
                title=kwargs.get("title"),
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=focused.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.exception("WindowFocusTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to focus window: {exc}",
            )


class WindowListTool(BaseTool):
    """List all open VR windows."""

    name = "window_list"
    description = "List all open VR windows and their state (positions, sizes, focus)."
    required_permissions = ["window.list"]
    action_category = ActionCategory.READ_ONLY
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "workspace_id": {
                "type": "string",
                "description": "Optional workspace ID to filter windows.",
            },
        },
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            agent = self._get_agent()
            windows = agent.list_windows(workspace_id=kwargs.get("workspace_id"))
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=[w.model_dump(mode="json") for w in windows],
            )
        except Exception as exc:
            logger.exception("WindowListTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to list windows: {exc}",
            )


class WindowSnapLayoutTool(BaseTool):
    """Snap windows to an ergonomic layout."""

    name = "window_snap"
    description = "Snap all windows in a workspace into an ergonomic layout (curved_arc, flat_grid, free_floating)."
    required_permissions = ["window.snap"]
    action_category = ActionCategory.NORMAL
    risk_level = RiskLevel.LOW
    parameters_schema = {
        "type": "object",
        "properties": {
            "layout": {
                "type": "string",
                "description": "Layout mode (curved_arc, flat_grid, free_floating).",
                "default": "curved_arc",
            },
            "workspace_id": {
                "type": "string",
                "description": "Workspace ID to snap.",
                "default": "workspace_1",
            },
            "user_position": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "description": "User head position coordinates.",
            },
            "user_forward": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "description": "User head forward vector.",
            },
        },
    }

    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def _get_agent(self) -> Any:
        return self._agent or get_default_window_agent()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            agent = self._get_agent()
            layout_str = kwargs.get("layout", "curved_arc")
            workspace_id = kwargs.get("workspace_id", "workspace_1")
            user_pos = (
                Vector3D(**kwargs["user_position"])
                if "user_position" in kwargs
                else None
            )
            user_fwd = (
                Vector3D(**kwargs["user_forward"])
                if "user_forward" in kwargs
                else None
            )

            positions = await agent.snap_to_layout(
                layout=layout_str,
                workspace_id=workspace_id,
                user_position=user_pos,
                user_forward=user_fwd,
            )
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={w_id: pos.model_dump() for w_id, pos in positions.items()},
            )
        except Exception as exc:
            logger.exception("WindowSnapLayoutTool failed")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to snap layout: {exc}",
            )


def create_window_tools(agent: Any = None) -> list[BaseTool]:
    """Factory creating all window tools bound to an optional WindowAgent."""
    return [
        WindowCreateTool(agent),
        WindowCloseTool(agent),
        WindowMoveTool(agent),
        WindowResizeTool(agent),
        WindowRotateTool(agent),
        WindowFocusTool(agent),
        WindowListTool(agent),
        WindowSnapLayoutTool(agent),
    ]
