"""Canonical data models for VR window management.

These types live in the Python layer and represent the *logical* state of
every window.  Unity never sees these classes directly — they are serialized
to JSON commands that flow over the IPC bridge.

Design notes
────────────
* ``VRWindow`` is the single source of truth for any window.
* Spatial primitives (``Vec3``, ``Quat``) mirror Unity's conventions
  so JSON round-trips are lossless.
* All models are Pydantic v2 ``BaseModel`` subclasses for automatic
  serialization, validation, and schema generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────

class WindowState(str, Enum):
    """Lifecycle state of a VR window."""

    CREATING  = "creating"       # command sent, Unity hasn't ack'd
    OPEN      = "open"           # visible and interactive
    MINIMIZED = "minimized"      # hidden but alive
    MAXIMIZED = "maximized"      # fills the user's comfortable FOV
    CLOSING   = "closing"        # close requested, awaiting teardown ack
    CLOSED    = "closed"         # fully destroyed


class WindowAnchor(str, Enum):
    """Where a window is logically anchored in the VR space."""

    WORLD_FIXED    = "world_fixed"       # stays at an absolute world position
    HEAD_RELATIVE  = "head_relative"     # lazy-follows the user's gaze
    HAND_ATTACHED  = "hand_attached"     # pinned to a controller
    WORKSPACE_SLOT = "workspace_slot"    # managed by WorkspaceArea layout


# ── Spatial Primitives ───────────────────────────────────────────────────

class Vec3(BaseModel):
    """3-component vector (matches Unity's Vector3 serialization)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(x=self.x + other.x, y=self.y + other.y, z=self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(x=self.x - other.x, y=self.y - other.y, z=self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(x=self.x * scalar, y=self.y * scalar, z=self.z * scalar)

    def magnitude(self) -> float:
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5

    def normalized(self) -> Vec3:
        mag = self.magnitude()
        if mag < 1e-8:
            return Vec3()
        return self * (1.0 / mag)


class Quat(BaseModel):
    """Quaternion rotation (matches Unity's Quaternion serialization).

    Identity rotation is (0, 0, 0, 1).
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    @classmethod
    def identity(cls) -> Quat:
        return cls(x=0.0, y=0.0, z=0.0, w=1.0)

    @classmethod
    def from_euler_y(cls, degrees: float) -> Quat:
        """Create a quaternion from a Y-axis rotation (common for VR window placement)."""
        import math
        rad = math.radians(degrees) / 2.0
        return cls(x=0.0, y=math.sin(rad), z=0.0, w=math.cos(rad))


class WindowTransform(BaseModel):
    """Full spatial pose of a window in VR space."""

    position: Vec3 = Field(default_factory=Vec3)
    rotation: Quat = Field(default_factory=Quat)
    scale: Vec3 = Field(default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0))


class WindowSize(BaseModel):
    """Logical panel dimensions in meters (world units)."""

    width: float = 0.8     # meters
    height: float = 0.5    # meters


# ── Core Window Record ──────────────────────────────────────────────────

class VRWindow(BaseModel):
    """Canonical window record — Python is the source of truth.

    One instance per managed window.  Changes to this model are
    published through the EventBus and forwarded to Unity.

    Attributes:
        window_id:       Unique identifier (auto-generated).
        title:           Human-readable window title.
        app_id:          Links to AppAgent's application identity.
        workspace_index: Which virtual desktop this window belongs to.
        state:           Current lifecycle state.
        anchor:          Spatial anchoring mode.
        transform:       Full 3D pose (position, rotation, scale).
        size:            Panel dimensions in meters.
        z_order:         Depth ordering — higher values are in front.
        is_focused:      Whether this window is the active focus target.
        created_at:      UTC timestamp of creation.
        metadata:        Extensible key-value store for app-specific data.
    """

    window_id: str = Field(default_factory=lambda: f"win_{uuid4().hex[:10]}")
    title: str = "Untitled"
    app_id: str = ""
    workspace_index: int = 0
    state: WindowState = WindowState.CREATING
    anchor: WindowAnchor = WindowAnchor.WORLD_FIXED

    # Spatial
    transform: WindowTransform = Field(default_factory=WindowTransform)
    size: WindowSize = Field(default_factory=WindowSize)

    # Z-order / focus
    z_order: int = 0
    is_focused: bool = False

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
