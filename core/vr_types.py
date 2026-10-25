"""VR Window Manager protocol types for NEXUS OS.

Defines the data contracts that flow between the Python agent layer
and the Unity VR shell across the WebSocket bridge.  Every type here
has a C# mirror in ``vr/Assets/Scripts/WindowManager/VRWindowTypes.cs``.

Hierarchy:
    Spatial primitives  →  Vector3D, Quaternion3D, WindowSize
    Enums               →  WindowContentType, WindowCommandType, WindowEventType
    Protocol models     →  WindowState, WindowCommand, WindowEvent
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Spatial primitives
# ---------------------------------------------------------------------------

class Vector3D(BaseModel):
    """A point or direction in 3-D world space (meters)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    # ── convenience factories ────────────────────────────────────────────

    @classmethod
    def zero(cls) -> Vector3D:
        return cls(x=0.0, y=0.0, z=0.0)

    @classmethod
    def one(cls) -> Vector3D:
        return cls(x=1.0, y=1.0, z=1.0)

    @classmethod
    def forward(cls) -> Vector3D:
        """Unity convention: +Z is forward."""
        return cls(x=0.0, y=0.0, z=1.0)

    # ── arithmetic ───────────────────────────────────────────────────────

    def __add__(self, other: Vector3D) -> Vector3D:
        return Vector3D(x=self.x + other.x, y=self.y + other.y, z=self.z + other.z)

    def __sub__(self, other: Vector3D) -> Vector3D:
        return Vector3D(x=self.x - other.x, y=self.y - other.y, z=self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3D:
        return Vector3D(x=self.x * scalar, y=self.y * scalar, z=self.z * scalar)

    def magnitude(self) -> float:
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5

    def __repr__(self) -> str:
        return f"Vector3D({self.x:.3f}, {self.y:.3f}, {self.z:.3f})"


class Quaternion3D(BaseModel):
    """Rotation in 3-D space as a unit quaternion.

    Uses the (x, y, z, w) convention matching Unity's ``Quaternion``.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0  # identity rotation

    @classmethod
    def identity(cls) -> Quaternion3D:
        return cls(x=0.0, y=0.0, z=0.0, w=1.0)

    @classmethod
    def from_euler(
        cls, pitch_deg: float = 0.0, yaw_deg: float = 0.0, roll_deg: float = 0.0
    ) -> Quaternion3D:
        """Convert Euler angles (pitch=X, yaw=Y, roll=Z in degrees) to a Quaternion."""
        p = math.radians(pitch_deg) * 0.5
        y = math.radians(yaw_deg) * 0.5
        r = math.radians(roll_deg) * 0.5

        sin_p = math.sin(p)
        cos_p = math.cos(p)
        sin_y = math.sin(y)
        cos_y = math.cos(y)
        sin_r = math.sin(r)
        cos_r = math.cos(r)

        return cls(
            x=sin_p * cos_y * cos_r - cos_p * sin_y * sin_r,
            y=cos_p * sin_y * cos_r + sin_p * cos_y * sin_r,
            z=cos_p * cos_y * sin_r - sin_p * sin_y * cos_r,
            w=cos_p * cos_y * cos_r + sin_p * sin_y * sin_r,
        )

    def __repr__(self) -> str:
        return f"Quaternion3D({self.x:.3f}, {self.y:.3f}, {self.z:.3f}, {self.w:.3f})"


class WindowSize(BaseModel):
    """Width × Height of a VR window in meters."""

    width: float = 0.8   # ~80 cm default
    height: float = 0.5  # ~50 cm default

    def area(self) -> float:
        return self.width * self.height

    def __repr__(self) -> str:
        return f"WindowSize({self.width:.2f}m × {self.height:.2f}m)"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WindowContentType(str, Enum):
    """What a VR window renders inside its frame."""

    TERMINAL = "terminal"
    WEB_BROWSER = "web_browser"
    FILE_BROWSER = "file_browser"
    TEXT_EDITOR = "text_editor"
    SYSTEM_MONITOR = "system_monitor"
    MEDIA_PLAYER = "media_player"
    AI_CHAT = "ai_chat"
    CUSTOM = "custom"


class WindowCommandType(str, Enum):
    """Operation types sent from Python → Unity."""

    CREATE = "create"
    CLOSE = "close"
    MOVE = "move"
    RESIZE = "resize"
    ROTATE = "rotate"
    FOCUS = "focus"
    UNFOCUS = "unfocus"
    SET_VISIBILITY = "set_visibility"
    SET_TITLE = "set_title"
    SET_CONTENT = "set_content"
    PIN = "pin"
    UNPIN = "unpin"
    SNAP_TO_LAYOUT = "snap_to_layout"
    BATCH = "batch"


class WindowEventType(str, Enum):
    """Interaction and acknowledgement events sent from Unity → Python."""

    INTERACTION_GRAB_START = "interaction_grab_start"
    INTERACTION_GRAB_END = "interaction_grab_end"
    INTERACTION_RESIZE_START = "interaction_resize_start"
    INTERACTION_RESIZE_END = "interaction_resize_end"
    INTERACTION_FOCUS_REQUEST = "interaction_focus_request"
    INTERACTION_CLOSE_REQUEST = "interaction_close_request"
    POSITION_CHANGED = "position_changed"
    ROTATION_CHANGED = "rotation_changed"
    SIZE_CHANGED = "size_changed"
    WINDOW_CREATED_ACK = "window_created_ack"
    WINDOW_CLOSED_ACK = "window_closed_ack"
    ERROR = "error"


class WindowLayoutMode(str, Enum):
    """Spatial arrangement algorithm for tiling windows."""

    CURVED_ARC = "curved_arc"
    FLAT_GRID = "flat_grid"
    FREE_FLOATING = "free_floating"


# ---------------------------------------------------------------------------
# Protocol models
# ---------------------------------------------------------------------------

class WindowState(BaseModel):
    """Canonical, serializable state of a single VR window.

    This is the authoritative record owned by the Python-side
    ``WindowStateStore``.  A snapshot is sent to Unity on CREATE and
    can be re-sent in bulk for state reconciliation.
    """

    window_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    app_id: str | None = None
    title: str = "Untitled Window"
    workspace_id: str = "workspace_1"

    # Spatial transform
    position: Vector3D = Field(default_factory=Vector3D.zero)
    rotation: Quaternion3D = Field(default_factory=Quaternion3D.identity)
    size: WindowSize = Field(default_factory=WindowSize)

    # Display state
    z_order: int = 0
    is_focused: bool = False
    is_visible: bool = True
    is_pinned: bool = False

    # Content
    content_type: WindowContentType = WindowContentType.CUSTOM
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class WindowCommand(BaseModel):
    """Message sent Python → Unity to mutate window state in VR.

    The ``payload`` dict carries command-specific parameters.
    See the architecture document for the full payload spec per command type.
    """

    command_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    command_type: WindowCommandType
    window_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class WindowEvent(BaseModel):
    """Message sent Unity → Python to report interaction or state changes.

    Events flow back through the bridge so the ``WindowAgent`` can
    update the authoritative ``WindowStateStore``.
    """

    event_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    event_type: WindowEventType
    window_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
