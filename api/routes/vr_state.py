"""Authenticated read-only VR state and workspace snapshots."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from api.dependencies import get_authenticated_session
from api.schemas import VRStateResponse, VRWorkspaceResponse, WorkspaceSnapshot
from security.sessions import AuthenticatedSession
from vr.window_protocol import PROTOCOL_VERSION
from vr.window_registry import WindowRegistry

router = APIRouter(prefix="/api/v1/vr", tags=["vr"])


def _window_snapshot(registry: WindowRegistry) -> list[dict]:
    """Serialize the registry's current records without creating new state."""
    return [window.model_dump(mode="json") for window in registry.get_all()]


@router.get("/state", response_model=VRStateResponse)
async def get_vr_state(
    request: Request,
    _session: AuthenticatedSession = Depends(get_authenticated_session),
) -> VRStateResponse:
    """Return the current authoritative Python-side VR window snapshot."""
    registry: WindowRegistry = request.app.state.window_registry
    windows = _window_snapshot(registry)
    focused = registry.get_focused()
    return VRStateResponse(
        protocol_version=PROTOCOL_VERSION,
        windows=windows,
        focused_window_id=focused.window_id if focused else None,
        window_count=len(windows),
    )


@router.get("/workspace", response_model=VRWorkspaceResponse)
async def get_vr_workspace(
    request: Request,
    _session: AuthenticatedSession = Depends(get_authenticated_session),
) -> VRWorkspaceResponse:
    """Return existing workspace metadata grouped with VR window records."""
    registry: WindowRegistry = request.app.state.window_registry
    windows = registry.get_all()
    workspaces = request.app.state.context.environment.workspaces
    snapshots = [
        WorkspaceSnapshot(
            index=workspace.index,
            name=workspace.name,
            is_active=workspace.is_active,
            windows=[
                window.model_dump(mode="json")
                for window in windows
                if window.workspace_index == workspace.index
            ],
        )
        for workspace in workspaces
    ]
    active = next((workspace.index for workspace in workspaces if workspace.is_active), None)
    return VRWorkspaceResponse(
        protocol_version=PROTOCOL_VERSION,
        active_workspace_index=active,
        workspaces=snapshots,
    )