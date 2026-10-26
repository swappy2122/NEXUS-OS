"""Authenticated WebSocket transport for the Unity VR client."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from api.connection_manager import ConnectionManager
from security.sessions import InvalidSessionToken, SessionManager
from security.exceptions import SecurityError
from vr.window_protocol import (
    NexusMessageType,
    SessionHeartbeatPayload,
    build_nexus_message,
    parse_nexus_message,
    AIRequestPayload,
    AIStatePayload,
    AITokenPayload,
    AIErrorPayload,
)

logger = logging.getLogger("nexus.api.vr")
router = APIRouter(tags=["vr"])


def _authorization_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _error_message(code: str) -> str:
    return build_nexus_message(
        NexusMessageType.WINDOW_ERROR,
        {"error_message": code},
    ).to_json()


async def _send_ai_message(websocket: WebSocket, message_type: NexusMessageType, payload: object, *, session_id: str, correlation_id: str | None = None) -> None:
    message = build_nexus_message(
        message_type,
        payload,
        session_id=session_id,
        correlation_id=correlation_id,
    )
    await websocket.send_text(message.to_json())


@router.websocket("/ws/v1/vr")
async def vr_websocket(websocket: WebSocket) -> None:
    """Authenticate and serve one Unity VR WebSocket connection."""
    sessions: SessionManager = websocket.app.state.session_manager
    manager: ConnectionManager = websocket.app.state.vr_connections
    permission_gate = websocket.app.state.permission_gate
    token = _authorization_token(websocket)
    if token is None:
        await websocket.close(code=1008)
        return
    try:
        session = sessions.resolve(token)
    except InvalidSessionToken:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    connection_id = await manager.register(websocket, session)
    try:
        while True:
            raw = await websocket.receive_text()
            await manager.touch(connection_id)
            if len(raw.encode("utf-8")) > 1_048_576:
                await websocket.send_text(_error_message("message_too_large"))
                continue
            try:
                message = parse_nexus_message(raw)
            except (ValueError, TypeError):
                await websocket.send_text(_error_message("invalid_message"))
                continue

            if message.message_type == NexusMessageType.AI_REQUEST.value:
                if permission_gate is None:
                    await websocket.send_text(_error_message("authorization_unavailable"))
                    continue
                try:
                    permission_gate.check_protocol_action(
                        agent_role="vr_session",
                        action_name="ai.request",
                        arguments={"session_id": session.session_id},
                        required_scopes=["ai.request"],
                    )
                except SecurityError:
                    await websocket.send_text(_error_message("operation_not_authorized"))
                    continue

                request_payload = message.payload
                if not isinstance(request_payload, AIRequestPayload):
                    await websocket.send_text(_error_message("invalid_ai_request"))
                    continue
                response_id = f"resp_{uuid4().hex[:12]}"
                agent_role = "supervisor"
                try:
                    await _send_ai_message(
                        websocket,
                        NexusMessageType.AI_STATE,
                        AIStatePayload(
                            agent_role=agent_role,
                            state="thinking",
                            user_message_id=request_payload.user_message_id,
                        ),
                        session_id=session.session_id,
                        correlation_id=message.message_id,
                    )
                    async for delta in websocket.app.state.model_router.stream_chat(
                        [{"role": "user", "content": request_payload.prompt}],
                        agent_role=agent_role,
                    ):
                        if delta:
                            await _send_ai_message(
                                websocket,
                                NexusMessageType.AI_TOKEN,
                                AITokenPayload(
                                    response_id=response_id,
                                    token=delta,
                                    is_final=False,
                                    agent_role=agent_role,
                                ),
                                session_id=session.session_id,
                                correlation_id=message.message_id,
                            )
                    await _send_ai_message(
                        websocket,
                        NexusMessageType.AI_TOKEN,
                        AITokenPayload(
                            response_id=response_id,
                            token="",
                            is_final=True,
                            agent_role=agent_role,
                        ),
                        session_id=session.session_id,
                        correlation_id=message.message_id,
                    )
                    await _send_ai_message(
                        websocket,
                        NexusMessageType.AI_STATE,
                        AIStatePayload(
                            agent_role=agent_role,
                            state="idle",
                            user_message_id=request_payload.user_message_id,
                        ),
                        session_id=session.session_id,
                        correlation_id=message.message_id,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await _send_ai_message(
                        websocket,
                        NexusMessageType.AI_ERROR,
                        AIErrorPayload(
                            response_id=response_id,
                            error="AI response generation failed",
                            agent_role=agent_role,
                        ),
                        session_id=session.session_id,
                        correlation_id=message.message_id,
                    )
                continue

            if message.message_type == NexusMessageType.SESSION_HEARTBEAT.value:
                heartbeat = message.payload
                if not isinstance(heartbeat, SessionHeartbeatPayload):
                    await websocket.send_text(_error_message("invalid_heartbeat"))
                    continue
                response = build_nexus_message(
                    NexusMessageType.SESSION_HEARTBEAT,
                    heartbeat,
                    session_id=session.session_id,
                    correlation_id=message.message_id,
                )
                await websocket.send_text(response.to_json())
                continue

            if message.message_type not in {
                NexusMessageType.WINDOW_CREATED.value,
                NexusMessageType.WINDOW_CLOSED.value,
                NexusMessageType.WINDOW_MOVED.value,
                NexusMessageType.WINDOW_RESIZED.value,
                NexusMessageType.WINDOW_ROTATED.value,
                NexusMessageType.WINDOW_FOCUSED.value,
                NexusMessageType.WINDOW_STATE_CHANGED.value,
                NexusMessageType.WINDOW_GRAB_STARTED.value,
                NexusMessageType.WINDOW_GRAB_ENDED.value,
                NexusMessageType.WINDOW_ERROR.value,
            }:
                await websocket.send_text(_error_message("unsupported_message_type"))
                continue

            payload = message.model_dump(mode="json").get("payload", {})
            if permission_gate is None:
                await websocket.send_text(_error_message("authorization_unavailable"))
                continue
            try:
                permission_gate.check_protocol_action(
                    agent_role="vr_session",
                    action_name=message.message_type,
                    arguments={
                        "window_id": payload.get("window_id", ""),
                        "session_id": session.session_id,
                    },
                    required_scopes=["window.interact"],
                )
            except SecurityError:
                await websocket.send_text(_error_message("operation_not_authorized"))
                continue

            event_data = message.model_dump(mode="json")
            payload = event_data.get("payload", {})
            event_data.update(
                {
                    "type": message.message_type,
                    "window_id": payload.get("window_id", ""),
                    "request_id": message.correlation_id or "",
                    "session_id": session.session_id,
                }
            )
            await websocket.app.state.event_bus.publish(
                f"window.event.{message.message_type.split('.', 1)[1]}",
                event_data,
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        if websocket.client_state == WebSocketState.CONNECTED:
            logger.debug("VR WebSocket connection ended unexpectedly")
    finally:
        await manager.remove(connection_id)