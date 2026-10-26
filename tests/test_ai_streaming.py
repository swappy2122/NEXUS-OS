"""Tests for authenticated AI response streaming over the VR WebSocket."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.connection_manager import ConnectionManager
from api.routes.vr import router
from core.event_bus import EventBus
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES
from security.sessions import SessionManager
from vr.window_protocol import AIRequestPayload, NexusMessageType, build_nexus_message


class FakeStreamingRouter:
    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks or ["one", " two", " three"]
        self.error = error

    async def stream_chat(self, messages, *, agent_role="*", **kwargs):
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk


def make_app(model_router: FakeStreamingRouter) -> tuple[FastAPI, SessionManager]:
    app = FastAPI()
    sessions = SessionManager()
    app.state.session_manager = sessions
    app.state.event_bus = EventBus()
    app.state.vr_connections = ConnectionManager(app.state.event_bus)
    app.state.permission_gate = PermissionGate(DEFAULT_POLICIES)
    app.state.model_router = model_router
    app.include_router(router)
    return app, sessions


def request_message(prompt: str = "hello") -> str:
    return build_nexus_message(
        NexusMessageType.AI_REQUEST,
        AIRequestPayload(prompt=prompt, user_message_id="user_1"),
    ).to_json()


def test_ai_chunks_are_ordered_correlated_and_complete_once() -> None:
    app, sessions = make_app(FakeStreamingRouter())
    created = sessions.create_session()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/vr",
            headers={"Authorization": f"Bearer {created.token}"},
        ) as websocket:
            websocket.send_text(request_message())
            messages = [json.loads(websocket.receive_text()) for _ in range(6)]

    tokens = [m for m in messages if m["message_type"] == "ai.token"]
    assert [m["payload"]["token"] for m in tokens[:-1]] == ["one", " two", " three"]
    assert tokens[-1]["payload"]["is_final"] is True
    assert sum(m["payload"]["is_final"] for m in tokens) == 1
    assert len({m["payload"]["response_id"] for m in tokens}) == 1
    assert all(m["session_id"] == created.session.session_id for m in messages)


def test_provider_error_emits_sanitized_ai_error() -> None:
    app, sessions = make_app(FakeStreamingRouter(error=RuntimeError("secret provider detail")))
    created = sessions.create_session()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1/vr",
            headers={"Authorization": f"Bearer {created.token}"},
        ) as websocket:
            websocket.send_text(request_message())
            messages = [json.loads(websocket.receive_text()) for _ in range(2)]

    assert messages[0]["message_type"] == "ai.state"
    assert messages[1]["message_type"] == "ai.error"
    assert messages[1]["payload"]["error"] == "AI response generation failed"
    assert "secret provider detail" not in json.dumps(messages)
