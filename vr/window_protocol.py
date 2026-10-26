"""Unified wire protocol and schemas for NEXUS OS (Python ↔ Unity VR Shell).

Every message crossing the IPC bridge (WebSocket or REST events) adheres to
the ``NexusMessage[T]`` envelope standard with a versioned, typed payload.

Legacy helpers (``WindowCommand``, ``WindowEvent``, ``build_command``) are
fully preserved for backwards compatibility with existing WindowAgent logic.

Namespaces supported:
  - ``window.*``: Window lifecycle and spatial manipulation commands/events
  - ``ai.*``: AI agent state, streaming tokens, and prompt requests
  - ``security.*``: Human-in-the-loop security confirmation dialogs
  - ``session.*``: Connection lifecycle, handshake, and heartbeat ping/pong
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from vr.window_types import (
    Quat,
    Vec3,
    WindowAnchor,
    WindowSize,
    WindowState,
    WindowTransform,
)

# ── Protocol Constants ──────────────────────────────────────────────────

PROTOCOL_VERSION: str = "1.0"


class NexusTopic(str, Enum):
    """Event topics matching NEXUS OS EventBus channels."""

    WINDOW = "window"
    AI = "ai"
    SECURITY = "security"
    SESSION = "session"
    SYSTEM = "system"


class NexusMessageType(str, Enum):
    """Standard message types across all NEXUS OS communication channels."""

    # Window commands (Python → Unity)
    WINDOW_CREATE = "window.create"
    WINDOW_CLOSE = "window.close"
    WINDOW_MOVE = "window.move"
    WINDOW_RESIZE = "window.resize"
    WINDOW_ROTATE = "window.rotate"
    WINDOW_FOCUS = "window.focus"
    WINDOW_SET_STATE = "window.set_state"
    WINDOW_SET_ANCHOR = "window.set_anchor"
    WINDOW_SET_TITLE = "window.set_title"
    WINDOW_BATCH = "window.batch"

    # Window events (Unity → Python)
    WINDOW_CREATED = "window.created"
    WINDOW_CLOSED = "window.closed"
    WINDOW_MOVED = "window.moved"
    WINDOW_RESIZED = "window.resized"
    WINDOW_ROTATED = "window.rotated"
    WINDOW_FOCUSED = "window.focused"
    WINDOW_STATE_CHANGED = "window.state_changed"
    WINDOW_GRAB_STARTED = "window.grab_started"
    WINDOW_GRAB_ENDED = "window.grab_ended"
    WINDOW_ERROR = "window.error"

    # AI interaction & streaming
    AI_REQUEST = "ai.request"
    AI_TOKEN = "ai.token"
    AI_STATE = "ai.state"
    AI_ERROR = "ai.error"

    # Security confirmation flow
    SECURITY_CONFIRM_REQUEST = "security.confirm_request"
    SECURITY_CONFIRM_RESPONSE = "security.confirm_response"

    # Session lifecycle
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    SESSION_HEARTBEAT = "session.heartbeat"


# ── Timestamp & ID Helpers ──────────────────────────────────────────────

def current_utc_timestamp_iso() -> str:
    """Return canonical ISO 8601 UTC timestamp format: YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_message_id(prefix: str = "msg") -> str:
    """Generate a unique random message identifier."""
    return f"{prefix}_{uuid4().hex[:12]}"


# ── Base Envelope ───────────────────────────────────────────────────────

T = TypeVar("T")


class NexusMessage(BaseModel, Generic[T]):
    """Unified wire envelope for all NEXUS Python ↔ Unity IPC communication.

    Attributes:
        protocol_version: Wire protocol revision (default: "1.0").
        message_id: Unique identifier for deduplication and logging.
        message_type: Semantic message type (e.g. "window.create", "ai.token").
        topic: High-level category or routing channel (e.g. "window", "ai").
        timestamp: ISO 8601 UTC timestamp string.
        session_id: Optional session identity token.
        correlation_id: Optional ID linking responses to original requests.
        payload: Typed payload model or dictionary.
    """

    protocol_version: str = PROTOCOL_VERSION
    message_id: str = Field(default_factory=generate_message_id)
    message_type: str
    topic: str
    timestamp: str = Field(default_factory=current_utc_timestamp_iso)
    session_id: str | None = None
    correlation_id: str | None = None
    payload: T

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_format(cls, v: str) -> str:
        """Ensure timestamp is valid ISO 8601."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, TypeError) as err:
            raise ValueError(f"timestamp must be a valid ISO 8601 string: {v}") from err
        return v

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol_version(cls, v: str) -> str:
        """Reject protocol versions this implementation cannot interpret."""
        if v != PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported protocol_version {v!r}; expected {PROTOCOL_VERSION!r}"
            )
        return v

    @field_validator("message_type", "topic")
    @classmethod
    def validate_non_empty_identifier(cls, v: str) -> str:
        """Require non-empty routing identifiers in every envelope."""
        if not v.strip():
            raise ValueError("message_type and topic must not be empty")
        return v

    @model_validator(mode="after")
    def validate_known_topic(self) -> NexusMessage[T]:
        """Keep registered message namespaces aligned with their topics."""
        if self.message_type in PAYLOAD_TYPE_REGISTRY:
            expected_topic = self.message_type.split(".", 1)[0]
            if self.topic != expected_topic:
                raise ValueError(
                    f"topic {self.topic!r} does not match message_type "
                    f"{self.message_type!r}; expected {expected_topic!r}"
                )
        return self

    def to_json(self) -> str:
        """Serialize envelope and payload to JSON string."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> NexusMessage[Any]:
        """Deserialize raw JSON into NexusMessage."""
        return cls.model_validate_json(raw)


# ── Typed Payload Models: Window Namespace ──────────────────────────────

class CreatePayload(BaseModel):
    """Payload for ``window.create`` commands."""

    window_id: str = Field(default_factory=lambda: f"win_{uuid4().hex[:8]}")
    title: str = "Untitled"
    app_id: str = ""
    workspace_index: int = 0
    transform: WindowTransform = Field(default_factory=WindowTransform)
    size: WindowSize = Field(default_factory=WindowSize)
    anchor: WindowAnchor = WindowAnchor.WORLD_FIXED


class WindowClosePayload(BaseModel):
    """Payload for a typed ``window.close`` command."""

    window_id: str


class MovePayload(BaseModel):
    """Payload for ``window.move`` commands."""

    window_id: str = ""
    target_position: Vec3
    animate: bool = True
    duration_seconds: float = 0.3


class ResizePayload(BaseModel):
    """Payload for ``window.resize`` commands."""

    window_id: str = ""
    target_size: WindowSize
    animate: bool = True
    duration_seconds: float = 0.2


class RotatePayload(BaseModel):
    """Payload for ``window.rotate`` commands."""

    window_id: str = ""
    target_rotation: Quat
    animate: bool = True
    duration_seconds: float = 0.3


class FocusPayload(BaseModel):
    """Payload for ``window.focus`` commands."""

    window_id: str = ""
    focused: bool = True


class SetStatePayload(BaseModel):
    """Payload for ``window.set_state`` commands."""

    window_id: str = ""
    target_state: WindowState


class SetAnchorPayload(BaseModel):
    """Payload for ``window.set_anchor`` commands."""

    anchor: WindowAnchor


class SetTitlePayload(BaseModel):
    """Payload for ``window.set_title`` commands."""

    title: str


# Window Event Payloads (Unity → Python)

class WindowCreatedPayload(BaseModel):
    """Payload emitted when Unity completes window instantiation."""

    window_id: str
    title: str = ""
    workspace_index: int = 0
    app_id: str = ""


class WindowClosedPayload(BaseModel):
    """Payload emitted when a window is closed and destroyed."""

    window_id: str


class WindowMovedPayload(BaseModel):
    """Payload emitted when a window position updates in VR."""

    window_id: str
    position: Vec3
    reason: str = "user_grab"


class WindowResizedPayload(BaseModel):
    """Payload emitted when a window size changes in VR."""

    window_id: str
    size: WindowSize


class WindowRotatedPayload(BaseModel):
    """Payload emitted when a window rotation updates in VR."""

    window_id: str
    rotation: Quat


class WindowFocusedPayload(BaseModel):
    """Payload emitted when a window gains or loses focus."""

    window_id: str
    focused: bool = True


class WindowStateChangedPayload(BaseModel):
    """Payload emitted when a window lifecycle state transitions."""

    window_id: str
    state: WindowState


class WindowGrabPayload(BaseModel):
    """Payload emitted during spatial grab interactions."""

    window_id: str
    hand: str = "right"  # "left" | "right"
    is_grabbing: bool = True


class WindowErrorPayload(BaseModel):
    """Payload emitted when an operation fails in Unity."""

    window_id: str = ""
    error_message: str
    request_id: str = ""


# ── Typed Payload Models: AI Namespace ──────────────────────────────────

class AIRequestPayload(BaseModel):
    """Payload sent from VR UI to invoke an AI query or command."""

    user_message_id: str = Field(default_factory=lambda: f"usr_{uuid4().hex[:8]}")
    prompt: str
    agent_role: str = "supervisor"
    session_id: str | None = None


class AITokenPayload(BaseModel):
    """Streaming chunk of AI text generation emitted to Unity VR UI."""

    response_id: str
    token: str
    is_final: bool = False
    agent_role: str = "supervisor"


class AIStatePayload(BaseModel):
    """Status updates for the AI Interaction Area and Status Orb."""

    agent_role: str = "supervisor"
    state: str = "idle"  # "idle" | "listening" | "thinking" | "responding" | "error"
    active_tool: str = ""
    user_message_id: str = ""


class AIErrorPayload(BaseModel):
    """Non-sensitive failure information for an AI response stream."""

    response_id: str
    error: str
    agent_role: str = "supervisor"


# ── Typed Payload Models: Security Namespace ────────────────────────────

class SecurityConfirmRequestPayload(BaseModel):
    """Pushed to Unity when a high-risk tool execution requires user confirmation."""

    confirmation_request_id: str
    agent_role: str
    tool_name: str
    action_category: str  # "read_only" | "normal" | "sensitive" | "destructive"
    risk_level: str  # "low" | "medium" | "high" | "critical"
    description: str
    expires_at: float
    parameters: dict[str, Any] = Field(default_factory=dict)


class SecurityConfirmResponsePayload(BaseModel):
    """Returned from Unity when the user approves or rejects an action."""

    confirmation_request_id: str
    decision: str  # "approved" | "rejected"
    reason: str = ""
    user_gesture: str = "spatial_pointer_click"


# ── Typed Payload Models: Session Namespace ─────────────────────────────

class SessionStartedPayload(BaseModel):
    """Handshake information when client connects or starts a session."""

    session_id: str
    client_id: str = "unity_vr_shell"
    client_version: str = "1.0.0"
    hmd_model: str = "DesktopSimulator"
    capabilities: list[str] = Field(default_factory=lambda: ["window", "ai", "security"])


class SessionEndedPayload(BaseModel):
    """Notification when a session terminates."""

    session_id: str
    reason: str = "client_shutdown"


class SessionHeartbeatPayload(BaseModel):
    """Liveness check exchanged periodically between Unity and Python."""

    timestamp_epoch_ms: int = Field(
        default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    sequence_number: int = 0


# ── Schema Registry & Factory ───────────────────────────────────────────

PAYLOAD_TYPE_REGISTRY: dict[str, type[BaseModel]] = {
    NexusMessageType.WINDOW_CREATE.value: CreatePayload,
    NexusMessageType.WINDOW_CLOSE.value: WindowClosePayload,
    NexusMessageType.WINDOW_MOVE.value: MovePayload,
    NexusMessageType.WINDOW_RESIZE.value: ResizePayload,
    NexusMessageType.WINDOW_ROTATE.value: RotatePayload,
    NexusMessageType.WINDOW_FOCUS.value: FocusPayload,
    NexusMessageType.WINDOW_SET_STATE.value: SetStatePayload,
    NexusMessageType.WINDOW_SET_ANCHOR.value: SetAnchorPayload,
    NexusMessageType.WINDOW_SET_TITLE.value: SetTitlePayload,
    NexusMessageType.WINDOW_CREATED.value: WindowCreatedPayload,
    NexusMessageType.WINDOW_CLOSED.value: WindowClosedPayload,
    NexusMessageType.WINDOW_MOVED.value: WindowMovedPayload,
    NexusMessageType.WINDOW_RESIZED.value: WindowResizedPayload,
    NexusMessageType.WINDOW_ROTATED.value: WindowRotatedPayload,
    NexusMessageType.WINDOW_FOCUSED.value: WindowFocusedPayload,
    NexusMessageType.WINDOW_STATE_CHANGED.value: WindowStateChangedPayload,
    NexusMessageType.WINDOW_GRAB_STARTED.value: WindowGrabPayload,
    NexusMessageType.WINDOW_GRAB_ENDED.value: WindowGrabPayload,
    NexusMessageType.WINDOW_ERROR.value: WindowErrorPayload,
    NexusMessageType.AI_REQUEST.value: AIRequestPayload,
    NexusMessageType.AI_TOKEN.value: AITokenPayload,
    NexusMessageType.AI_STATE.value: AIStatePayload,
    NexusMessageType.AI_ERROR.value: AIErrorPayload,
    NexusMessageType.SECURITY_CONFIRM_REQUEST.value: SecurityConfirmRequestPayload,
    NexusMessageType.SECURITY_CONFIRM_RESPONSE.value: SecurityConfirmResponsePayload,
    NexusMessageType.SESSION_STARTED.value: SessionStartedPayload,
    NexusMessageType.SESSION_ENDED.value: SessionEndedPayload,
    NexusMessageType.SESSION_HEARTBEAT.value: SessionHeartbeatPayload,
}


def build_nexus_message(
    message_type: str | NexusMessageType,
    payload: BaseModel | dict[str, Any],
    topic: str | NexusTopic | None = None,
    correlation_id: str | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
) -> NexusMessage[Any]:
    """Construct a validated NexusMessage instance from type and payload."""
    type_str = message_type.value if isinstance(message_type, NexusMessageType) else str(message_type)

    if topic is None:
        # Default topic derived from message_type prefix
        prefix = type_str.split(".")[0]
        topic_str = prefix
    elif isinstance(topic, NexusTopic):
        topic_str = topic.value
    else:
        topic_str = str(topic)

    payload_data: Any = payload
    if type_str in PAYLOAD_TYPE_REGISTRY and isinstance(payload, dict):
        payload_cls = PAYLOAD_TYPE_REGISTRY[type_str]
        payload_data = payload_cls.model_validate(payload)

    kwargs: dict[str, Any] = {
        "message_type": type_str,
        "topic": topic_str,
        "payload": payload_data,
        "correlation_id": correlation_id,
        "session_id": session_id,
    }
    if message_id:
        kwargs["message_id"] = message_id

    return NexusMessage(**kwargs)


def parse_nexus_message(raw: str | bytes | dict[str, Any]) -> NexusMessage[Any]:
    """Parse JSON or dict into a strongly-typed NexusMessage[T] using the registry."""
    if isinstance(raw, (str, bytes)):
        data = json.loads(raw)
    else:
        data = raw

    if not isinstance(data, dict):
        raise ValueError("Nexus message must be a JSON object")

    message_type = data.get("message_type")
    if not message_type:
        raise ValueError("Missing required field: message_type")

    payload_raw = data.get("payload", {})
    if message_type in PAYLOAD_TYPE_REGISTRY and isinstance(payload_raw, dict):
        payload_cls = PAYLOAD_TYPE_REGISTRY[message_type]
        data["payload"] = payload_cls.model_validate(payload_raw)

    return NexusMessage.model_validate(data)


# ── Backwards Compatibility Layer ───────────────────────────────────────
# Preserves existing WindowCommand, WindowEvent, and build_command signatures
# so existing WindowAgent and VRBridge implementations continue without change.

class WindowCommandType(str, Enum):
    """All imperative commands the Python layer can send to Unity (legacy enum)."""

    CREATE = "window.create"
    CLOSE = "window.close"
    MOVE = "window.move"
    RESIZE = "window.resize"
    ROTATE = "window.rotate"
    FOCUS = "window.focus"
    SET_STATE = "window.set_state"
    SET_ANCHOR = "window.set_anchor"
    SET_TITLE = "window.set_title"
    BATCH = "window.batch"


class WindowCommand(BaseModel):
    """Legacy command envelope sent from Python to Unity."""

    type: WindowCommandType
    window_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex[:8]}")


class WindowEventType(str, Enum):
    """All declarative events that Unity sends back to Python (legacy enum)."""

    CREATED = "window.created"
    CLOSED = "window.closed"
    MOVED = "window.moved"
    RESIZED = "window.resized"
    ROTATED = "window.rotated"
    FOCUSED = "window.focused"
    STATE_CHANGED = "window.state_changed"
    GRAB_STARTED = "window.grab_started"
    GRAB_ENDED = "window.grab_ended"
    ERROR = "window.error"


class WindowEvent(BaseModel):
    """Legacy acknowledgement or user-initiated event from Unity."""

    type: WindowEventType
    window_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    timestamp: float = 0.0


def build_command(
    cmd_type: WindowCommandType,
    window_id: str,
    payload: BaseModel | None = None,
    request_id: str = "",
) -> WindowCommand:
    """Convenience factory that serializes a typed payload model (legacy helper)."""
    return WindowCommand(
        type=cmd_type,
        window_id=window_id,
        payload=payload.model_dump(mode="json") if payload else {},
        request_id=request_id or f"req_{uuid4().hex[:8]}",
    )
