"""Tests for authenticated VR state and workspace snapshot endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.vr_state import router
from context.manager import ContextManager
from context.environment import WorkspaceInfo
from security.sessions import SessionManager
from vr.window_registry import WindowRegistry
from vr.window_types import Vec3, VRWindow, WindowSize, WindowState, WindowTransform


def make_app() -> tuple[FastAPI, SessionManager, WindowRegistry, ContextManager]:
    app = FastAPI()
    sessions = SessionManager()
    registry = WindowRegistry()
    context = ContextManager()
    app.state.session_manager = sessions
    app.state.window_registry = registry
    app.state.context = context
    app.include_router(router)
    return app, sessions, registry, context


def auth_header(sessions: SessionManager) -> dict[str, str]:
    return {"Authorization": f"Bearer {sessions.create_session().token}"}


def test_authenticated_empty_state_and_workspace() -> None:
    app, sessions, _, _ = make_app()
    headers = auth_header(sessions)

    with TestClient(app) as client:
        state = client.get("/api/v1/vr/state", headers=headers)
        workspace = client.get("/api/v1/vr/workspace", headers=headers)

    assert state.status_code == 200
    assert state.json() == {
        "protocol_version": "1.0",
        "windows": [],
        "focused_window_id": None,
        "window_count": 0,
    }
    assert workspace.status_code == 200
    assert workspace.json() == {
        "protocol_version": "1.0",
        "active_workspace_index": None,
        "workspaces": [],
    }


def test_state_returns_authoritative_window_properties() -> None:
    app, sessions, registry, _ = make_app()
    window = VRWindow(
        window_id="win_editor",
        title="Editor",
        app_id="code",
        workspace_index=1,
        state=WindowState.OPEN,
        transform=WindowTransform(position=Vec3(x=1.0, y=1.5, z=2.0)),
        size=WindowSize(width=1.2, height=0.8),
    )
    registry.add(window)
    registry.set_focus(window.window_id)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/vr/state",
            headers=auth_header(sessions),
        )

    body = response.json()
    assert body["window_count"] == 1
    assert body["focused_window_id"] == "win_editor"
    assert body["windows"][0]["window_id"] == "win_editor"
    assert body["windows"][0]["title"] == "Editor"
    assert body["windows"][0]["transform"]["position"] == {"x": 1.0, "y": 1.5, "z": 2.0}
    assert body["windows"][0]["size"] == {"width": 1.2, "height": 0.8}


def test_workspace_uses_context_metadata_and_groups_registry_windows() -> None:
    app, sessions, registry, context = make_app()
    context.update_workspaces([
        WorkspaceInfo(index=0, name="Main", is_active=True),
        WorkspaceInfo(index=1, name="Dev", is_active=False),
    ])
    registry.add(VRWindow(window_id="win_dev", title="Terminal", workspace_index=1))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/vr/workspace",
            headers=auth_header(sessions),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["active_workspace_index"] == 0
    assert body["workspaces"][0]["name"] == "Main"
    assert body["workspaces"][0]["windows"] == []
    assert body["workspaces"][1]["windows"][0]["window_id"] == "win_dev"


def test_missing_invalid_and_revoked_credentials_are_rejected() -> None:
    app, sessions, _, _ = make_app()
    created = sessions.create_session()
    sessions.revoke(created.session.session_id)

    with TestClient(app) as client:
        missing = client.get("/api/v1/vr/state")
        invalid = client.get(
            "/api/v1/vr/workspace",
            headers={"Authorization": "Bearer invalid"},
        )
        revoked = client.get(
            "/api/v1/vr/state",
            headers={"Authorization": f"Bearer {created.token}"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert revoked.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"