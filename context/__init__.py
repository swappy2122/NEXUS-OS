"""NEXUS OS Context Management Subsystem (Spatial & Conversation Memory)."""

from context.environment import (
    ActionType,
    AppInfo,
    EnvironmentContext,
    UserAction,
    WindowInfo,
    WorkspaceInfo,
)
from context.manager import ContextManager
from context.referent_resolver import ReferentResolver, ResolutionResult

__all__ = [
    "ContextManager",
    # Environment
    "EnvironmentContext",
    "ActionType",
    "AppInfo",
    "WindowInfo",
    "WorkspaceInfo",
    "UserAction",
    # Referent
    "ReferentResolver",
    "ResolutionResult",
]
