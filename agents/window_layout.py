"""Spatial window layout engine for NEXUS OS.

Computes world-space positions for a set of windows given a layout
mode and the user's current head position / forward direction.

Three layout algorithms:

* **CurvedArc** — windows arranged on a cylinder at comfort distance.
* **FlatGrid** — windows tiled in a flat plane grid in front of the user.
* **FreeFloating** — no layout enforcement; positions left unchanged.

The engine is stateless and deterministic — given the same inputs it
always produces the same output, making it easy to test and snapshot.
"""

from __future__ import annotations

import math
import logging
from typing import Protocol, runtime_checkable

from core.vr_types import Vector3D, WindowLayoutMode, WindowState

logger = logging.getLogger("nexus.window_layout")


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

@runtime_checkable
class IWindowLayoutEngine(Protocol):
    """Protocol for spatial layout computation.

    Given a list of windows and layout parameters, returns a mapping
    of ``window_id → Vector3D`` target positions.
    """

    def compute_positions(
        self,
        windows: list[WindowState],
        layout: WindowLayoutMode,
        user_position: Vector3D,
        user_forward: Vector3D,
    ) -> dict[str, Vector3D]: ...


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

class WindowLayoutEngine:
    """Computes spatial positions for VR windows.

    Configuration:
        comfort_distance:  Distance in meters from the user to the window arc.
        arc_span_degrees:  Total horizontal arc span for CurvedArc layout.
        eye_height:        Default vertical center for windows (meters).
        grid_columns:      Max columns per row for FlatGrid layout.
        grid_spacing:      Gap between windows in FlatGrid layout (meters).
    """

    def __init__(
        self,
        comfort_distance: float = 2.5,
        arc_span_degrees: float = 120.0,
        eye_height: float = 1.5,
        grid_columns: int = 3,
        grid_spacing: float = 0.15,
    ) -> None:
        self.comfort_distance = comfort_distance
        self.arc_span_degrees = arc_span_degrees
        self.eye_height = eye_height
        self.grid_columns = grid_columns
        self.grid_spacing = grid_spacing

    def compute_positions(
        self,
        windows: list[WindowState],
        layout: WindowLayoutMode,
        user_position: Vector3D,
        user_forward: Vector3D,
    ) -> dict[str, Vector3D]:
        """Dispatch to the appropriate layout algorithm.

        Returns:
            Mapping of window_id to computed world-space position.
        """
        if not windows:
            return {}

        if layout == WindowLayoutMode.CURVED_ARC:
            return self._curved_arc(windows, user_position, user_forward)
        elif layout == WindowLayoutMode.FLAT_GRID:
            return self._flat_grid(windows, user_position, user_forward)
        elif layout == WindowLayoutMode.FREE_FLOATING:
            return self._free_floating(windows)
        else:
            logger.warning("Unknown layout mode '%s', falling back to free floating", layout)
            return self._free_floating(windows)

    # ── layout algorithms ────────────────────────────────────────────────

    def _curved_arc(
        self,
        windows: list[WindowState],
        user_pos: Vector3D,
        user_fwd: Vector3D,
    ) -> dict[str, Vector3D]:
        """Arrange windows on a cylindrical arc around the user.

        The arc is centered on the user's forward direction, at
        ``comfort_distance`` meters out, spanning ``arc_span_degrees``.
        """
        n = len(windows)
        span_rad = math.radians(self.arc_span_degrees)

        # Base angle: direction the user is facing (atan2 of forward XZ)
        base_angle = math.atan2(user_fwd.x, user_fwd.z)

        positions: dict[str, Vector3D] = {}
        for i, window in enumerate(windows):
            if n == 1:
                angle = base_angle
            else:
                # Distribute evenly across the arc
                t = i / (n - 1)  # 0 → 1
                angle = base_angle + span_rad * (t - 0.5)

            x = user_pos.x + self.comfort_distance * math.sin(angle)
            z = user_pos.z + self.comfort_distance * math.cos(angle)
            y = self.eye_height

            positions[window.window_id] = Vector3D(x=x, y=y, z=z)

        logger.debug(
            "CurvedArc layout: %d windows, span=%.0f°, distance=%.1fm",
            n, self.arc_span_degrees, self.comfort_distance,
        )
        return positions

    def _flat_grid(
        self,
        windows: list[WindowState],
        user_pos: Vector3D,
        user_fwd: Vector3D,
    ) -> dict[str, Vector3D]:
        """Arrange windows in a flat grid plane facing the user.

        Windows are placed in rows of ``grid_columns``, centered
        horizontally in front of the user.
        """
        n = len(windows)
        cols = min(n, self.grid_columns)
        rows = math.ceil(n / cols)

        # Compute the right vector from the forward vector (Y-up cross)
        right = Vector3D(x=user_fwd.z, y=0.0, z=-user_fwd.x)
        mag = right.magnitude()
        if mag > 0.001:
            right = right * (1.0 / mag)

        positions: dict[str, Vector3D] = {}
        for i, window in enumerate(windows):
            col = i % cols
            row = i // cols

            # Center the grid horizontally
            col_offset = (col - (cols - 1) / 2.0) * (window.size.width + self.grid_spacing)
            # Stack rows top-down from eye height
            row_offset = -row * (window.size.height + self.grid_spacing)

            # Position: user + forward * distance + right * col_offset + up * row_offset
            x = (
                user_pos.x
                + user_fwd.x * self.comfort_distance
                + right.x * col_offset
            )
            z = (
                user_pos.z
                + user_fwd.z * self.comfort_distance
                + right.z * col_offset
            )
            y = self.eye_height + row_offset

            positions[window.window_id] = Vector3D(x=x, y=y, z=z)

        logger.debug(
            "FlatGrid layout: %d windows, %d cols × %d rows",
            n, cols, rows,
        )
        return positions

    def _free_floating(
        self,
        windows: list[WindowState],
    ) -> dict[str, Vector3D]:
        """Return current positions unchanged (no layout enforcement)."""
        return {
            w.window_id: w.position
            for w in windows
        }
