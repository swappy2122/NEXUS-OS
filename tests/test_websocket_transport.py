"""Tests for the authenticated FastAPI VR WebSocket transport."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.connection_manager import ConnectionManager
from api.routes.vr import router
from core.event_bus import EventBus
from security.sessions import SessionManager
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES
from vr.window_protocol import (
    NexusMessageType,
    SessionHeartbeatPayload,
    build_nexus_message,
)


def make_app() -> tuple[FastAPI, SessionManager, EventBus, ConnectionManager]:
    app = FastAPI()
    sessions = SessionManager()
    event_bus = EventBus()
    manager = ConnectionManager(event_bus)
    app.state.session_manager = sessions
    app.state.event_bus = event_bus
    app.state.vr_connections = manager
    app.state.permission_gate = PermissionGate(DEFAULT_POLICIES)
    app.include_router(router)
    return app, sessions, event_bus, manager


def test_authenticated_connection_and_heartbeat() -> None:
    app, sessions, _, manager = make_app()
    created = sessions.create_session()
    heartbeat = build_nexus_message(
        NexusMessageType.SESSION_HEARTBEAT,
        SessionHeartbeatPayload(sequence_number=4),
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/vr",
            headers={"Authorization": f"Bearer {created.token}"},
        ) as websocket:
            websocket.send_text(heartbeat.to_json())
            response = json.loads(websocket.receive_text())
            assert response["message_type"] == "session.heartbeat"
            assert response["correlation_id"] == heartbeat.message_id
            assert response["session_id"] == created.session.session_id
            assert manager.connection_count == 1
    assert manager.connection_count == 0


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_unauthorized_connection_is_rejected(headers: dict[str, str]) -> None:
    app, _, _, _ = make_app()
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/v1/vr", headers=headers):
                pass


def test_revoked_session_is_rejected() -> None:
    app, sessions, _, _ = make_app()
    created = sessions.create_session()
    sessions.revoke(created.session.session_id)
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws/v1/vr",
                headers={"Authorization": f"Bearer {created.token}"},
            ):
                pass


def test_malformed_and_unsupported_messages_receive_protocol_errors() -> None:
    app, sessions, _, _ = make_app()
    created = sessions.create_session()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/vr",
            headers={"Authorization": f"Bearer {created.token}"},
        ) as websocket:
            websocket.send_text("not-json")
            assert json.loads(websocket.receive_text())["payload"]["error_message"] == "invalid_message"

            unsupported = {
                "protocol_version": "1.0",
                "message_id": "msg_unsupported",
                "message_type": "session.started",
                "topic": "session",
                "timestamp": "2026-10-26T00:00:00Z",
                "payload": {"session_id": "sess_1"},
            }
            websocket.send_text(json.dumps(unsupported))
            assert json.loads(websocket.receive_text())["payload"]["error_message"] == "unsupported_message_type"


def test_valid_window_event_is_published_to_event_bus() -> None:
    app, sessions, event_bus, _ = make_app()
    created = sessions.create_session()
    received: list[dict] = []

    def listener(data: dict) -> None:
        received.append(data)

    event_bus.subscribe("window.event.created", listener)
    message = build_nexus_message(
        NexusMessageType.WINDOW_CREATED,
        {"window_id": "win_1"},
    )
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/vr",
            headers={"Authorization": f"Bearer {created.token}"},
        ) as websocket:
            websocket.send_text(message.to_json())
    assert received and received[0]["message_type"] == "window.created"
    assert received[0]["type"] == "window.created"
    assert received[0]["window_id"] == "win_1"


@pytest.mark.asyncio
async def test_event_bus_delivery_and_failed_client_isolated() -> None:
    event_bus = EventBus()
    manager = ConnectionManager(event_bus)
    good = AsyncMock()
    bad = AsyncMock()
    bad.send_text.side_effect = RuntimeError("closed")
    session_manager = SessionManager()
    session = session_manager.create_session().session

    good_id = await manager.register(good, session)  # type: ignore[arg-type]
    bad_id = await manager.register(bad, session)  # type: ignore[arg-type]
    await manager.start()
    await event_bus.publish(
        "window.command.close",
        {
            "type": "window.close",
            "window_id": "win_1",
            "payload": {},
            "request_id": "req_1",
        },
    )

    assert good.send_text.await_count == 1
    assert await manager.get(bad_id) is None
    assert await manager.get(good_id) is not None
    await manager.stop()


@pytest.mark.asyncio
async def test_stale_cleanup_and_subscription_lifecycle() -> None:
    now = [100.0]
    event_bus = EventBus()
    manager = ConnectionManager(event_bus, stale_timeout_seconds=10, clock=lambda: now[0])
    websocket = AsyncMock()
    session = SessionManager().create_session().session
    await manager.register(websocket, session)  # type: ignore[arg-type]
    await manager.start()
    assert manager.subscribed is True
    now[0] = 111.0
    assert await manager.cleanup_stale() == 1
    assert manager.connection_count == 0
    await manager.stop()
    assert manager.subscribed is False