"""Unit tests for the unified NEXUS wire protocol and schemas."""

import json
import pytest
from pydantic import ValidationError

from vr.window_protocol import (
    NexusMessage,
    NexusMessageType,
    NexusTopic,
    PROTOCOL_VERSION,
    build_nexus_message,
    parse_nexus_message,
    # Window payloads
    CreatePayload,
    WindowClosePayload,
    MovePayload,
    ResizePayload,
    RotatePayload,
    FocusPayload,
    SetStatePayload,
    WindowCreatedPayload,
    WindowMovedPayload,
    # AI payloads
    AIRequestPayload,
    AITokenPayload,
    AIStatePayload,
    # Security payloads
    SecurityConfirmRequestPayload,
    SecurityConfirmResponsePayload,
    # Session payloads
    SessionStartedPayload,
    SessionEndedPayload,
    SessionHeartbeatPayload,
    # Legacy compatibility
    WindowCommand,
    WindowCommandType,
    WindowEvent,
    WindowEventType,
    build_command,
)
from vr.window_types import Vec3, Quat, WindowSize, WindowState


class TestNexusEnvelope:
    """Tests for the generic NexusMessage[T] envelope."""

    def test_default_construction(self):
        msg = NexusMessage(
            message_type=NexusMessageType.AI_TOKEN.value,
            topic=NexusTopic.AI.value,
            payload={"token": "hello", "response_id": "r1"},
        )
        assert msg.protocol_version == PROTOCOL_VERSION
        assert msg.message_id.startswith("msg_")
        assert msg.topic == "ai"
        assert msg.message_type == "ai.token"
        assert msg.timestamp.endswith("Z")
        assert msg.session_id is None
        assert msg.correlation_id is None
        assert msg.payload == {"token": "hello", "response_id": "r1"}

    def test_timestamp_validation_valid_iso(self):
        msg = NexusMessage(
            message_type="test",
            topic="test",
            timestamp="2026-10-26T00:00:00Z",
            payload={},
        )
        assert msg.timestamp == "2026-10-26T00:00:00Z"

    def test_timestamp_validation_invalid(self):
        with pytest.raises(ValidationError):
            NexusMessage(
                message_type="test",
                topic="test",
                timestamp="invalid-timestamp",
                payload={},
            )

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            NexusMessage(topic="test", payload={})  # missing message_type

        with pytest.raises(ValidationError):
            NexusMessage(message_type="test", payload={})  # missing topic

    def test_unsupported_version_is_rejected(self):
        with pytest.raises(ValidationError, match="unsupported protocol_version"):
            NexusMessage(
                protocol_version="2.0",
                message_type="test",
                topic="test",
                payload={},
            )

    def test_known_message_requires_matching_topic(self):
        with pytest.raises(ValidationError, match="does not match message_type"):
            NexusMessage(
                message_type=NexusMessageType.WINDOW_CREATE.value,
                topic="ai",
                payload={},
            )


class TestPayloadValidation:
    """Tests for namespace-specific typed payloads."""

    def test_window_create_payload(self):
        payload = CreatePayload(
            title="Editor",
            app_id="code_editor",
            workspace_index=1,
            size=WindowSize(width=1.5, height=1.0),
        )
        msg = build_nexus_message(NexusMessageType.WINDOW_CREATE, payload)
        assert msg.topic == "window"
        assert msg.message_type == "window.create"
        assert isinstance(msg.payload, CreatePayload)
        assert msg.payload.title == "Editor"
        assert msg.payload.size.width == 1.5

    def test_window_close_payload_is_typed(self):
        msg = build_nexus_message(
            NexusMessageType.WINDOW_CLOSE,
            {"window_id": "win_01"},
        )
        assert isinstance(msg.payload, WindowClosePayload)
        assert msg.payload.window_id == "win_01"

    def test_ai_token_payload(self):
        payload = AITokenPayload(
            response_id="resp_01",
            token="Hello world",
            is_final=False,
            agent_role="supervisor",
        )
        msg = build_nexus_message(NexusMessageType.AI_TOKEN, payload)
        assert msg.topic == "ai"
        assert msg.message_type == "ai.token"
        assert msg.payload.token == "Hello world"
        assert not msg.payload.is_final

    def test_ai_state_payload(self):
        payload = AIStatePayload(
            agent_role="system_agent",
            state="thinking",
            active_tool="system_info",
        )
        msg = build_nexus_message(NexusMessageType.AI_STATE, payload)
        assert msg.topic == "ai"
        assert msg.payload.state == "thinking"
        assert msg.payload.active_tool == "system_info"

    def test_security_confirm_request_payload(self):
        payload = SecurityConfirmRequestPayload(
            confirmation_request_id="conf_123",
            agent_role="system_agent",
            tool_name="process_run",
            action_category="destructive",
            risk_level="high",
            description="Run command: rm -rf /tmp/test",
            expires_at=1729913000.0,
            parameters={"cmd": "rm -rf /tmp/test"},
        )
        msg = build_nexus_message(NexusMessageType.SECURITY_CONFIRM_REQUEST, payload)
        assert msg.topic == "security"
        assert msg.payload.risk_level == "high"
        assert msg.payload.action_category == "destructive"

    def test_security_confirm_response_payload(self):
        payload = SecurityConfirmResponsePayload(
            confirmation_request_id="conf_123",
            decision="approved",
            user_gesture="spatial_pointer_click",
        )
        msg = build_nexus_message(NexusMessageType.SECURITY_CONFIRM_RESPONSE, payload)
        assert msg.topic == "security"
        assert msg.payload.decision == "approved"

    def test_session_lifecycle_payloads(self):
        start = SessionStartedPayload(
            session_id="sess_001",
            client_id="unity_vr_shell",
            hmd_model="Quest 3",
            capabilities=["window", "ai"],
        )
        msg_start = build_nexus_message(NexusMessageType.SESSION_STARTED, start)
        assert msg_start.topic == "session"
        assert msg_start.payload.hmd_model == "Quest 3"

        heartbeat = SessionHeartbeatPayload(sequence_number=42)
        msg_hb = build_nexus_message(NexusMessageType.SESSION_HEARTBEAT, heartbeat)
        assert msg_hb.payload.sequence_number == 42


class TestSerializationAndParsing:
    """Tests for round-trip JSON serialization and typed parsing."""

    def test_round_trip_serialization(self):
        payload = MovePayload(
            target_position=Vec3(x=1.0, y=2.0, z=3.0),
            animate=True,
            duration_seconds=0.5,
        )
        msg = build_nexus_message(
            NexusMessageType.WINDOW_MOVE,
            payload,
            correlation_id="corr_99",
            session_id="sess_42",
        )
        json_str = msg.to_json()

        # Parse back using parse_nexus_message
        parsed = parse_nexus_message(json_str)
        assert parsed.message_id == msg.message_id
        assert parsed.message_type == "window.move"
        assert parsed.topic == "window"
        assert parsed.correlation_id == "corr_99"
        assert parsed.session_id == "sess_42"
        assert isinstance(parsed.payload, MovePayload)
        assert parsed.payload.target_position.x == 1.0
        assert parsed.payload.animate is True

    def test_canonical_json_envelope_parsing(self):
        canonical_json = json.dumps({
            "protocol_version": "1.0",
            "message_id": "example-message-001",
            "message_type": "window.create",
            "topic": "window",
            "timestamp": "2026-10-26T00:00:00Z",
            "session_id": None,
            "correlation_id": None,
            "payload": {
                "window_id": "window-001",
                "title": "NEXUS Workspace",
            },
        })
        parsed = parse_nexus_message(canonical_json)
        assert parsed.protocol_version == "1.0"
        assert parsed.message_id == "example-message-001"
        assert parsed.message_type == "window.create"
        assert parsed.topic == "window"
        assert parsed.timestamp == "2026-10-26T00:00:00Z"
        assert isinstance(parsed.payload, CreatePayload)
        assert parsed.payload.window_id == "window-001"
        assert parsed.payload.title == "NEXUS Workspace"

    def test_parse_invalid_payload_fails(self):
        invalid_json = json.dumps({
            "protocol_version": "1.0",
            "message_id": "bad-msg",
            "message_type": "security.confirm_request",
            "topic": "security",
            "timestamp": "2026-10-26T00:00:00Z",
            "payload": {
                # missing required fields: confirmation_request_id, agent_role, tool_name, etc.
                "invalid_field": 123
            },
        })
        with pytest.raises(ValidationError):
            parse_nexus_message(invalid_json)


class TestBackwardsCompatibility:
    """Verify existing WindowCommand and WindowEvent continue to function."""

    def test_legacy_build_command(self):
        payload = CreatePayload(title="Legacy Window")
        cmd = build_command(WindowCommandType.CREATE, "win_legacy_01", payload)
        assert cmd.type == WindowCommandType.CREATE
        assert cmd.window_id == "win_legacy_01"
        assert cmd.payload["title"] == "Legacy Window"
        assert cmd.request_id.startswith("req_")

    def test_legacy_window_event(self):
        evt = WindowEvent(
            type=WindowEventType.CREATED,
            window_id="win_01",
            payload={"ok": True},
            request_id="req_01",
            timestamp=123456.78,
        )
        assert evt.type == WindowEventType.CREATED
        assert evt.window_id == "win_01"
        assert evt.request_id == "req_01"
