"""
NEXUS OS — VR Shell Module.

Provides integration hooks, status diagnostics, and environment launch helpers
for the Unity-based OpenXR VR Shell.

Sub-modules:
    window_types    — Canonical data models (VRWindow, Vec3, Quat, etc.)
    window_protocol — IPC command/event protocol (WindowCommand, WindowEvent)
    window_registry — In-memory window state store
    vr_bridge       — WebSocket bridge to Unity
"""

from typing import Dict, Any

__version__ = "0.2.0-alpha"


def get_vr_shell_info() -> Dict[str, Any]:
    """Return status and configuration metadata for the Unity VR Shell."""
    return {
        "version": __version__,
        "engine": "Unity 6000.6.6f1",
        "xr_plugin": "OpenXR",
        "scene": "Assets/Scenes/NexusHome.unity",
        "areas": [
            "Application Area",
            "Workspace Area",
            "AI Interaction Area",
        ],
        "ui_features": [
            "Spatial HUD",
            "WorldSpace Canvases",
            "Simple Gaze Pointer",
            "Desktop Simulator Fallback",
            "VR Window Manager",
        ],
        "window_management": {
            "bridge_port": 9100,
            "protocol": "JSON over WebSocket",
            "supported_operations": [
                "create", "close", "move", "resize",
                "rotate", "focus", "set_state", "layout",
            ],
        },
    }

