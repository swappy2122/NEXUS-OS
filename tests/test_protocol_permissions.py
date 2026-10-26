"""Tests for PermissionGate enforcement at the VR protocol boundary."""

from __future__ import annotations

import pytest

from security.exceptions import PermissionDenied
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES


def test_allowed_vr_window_interaction_uses_explicit_policy() -> None:
    gate = PermissionGate(DEFAULT_POLICIES)

    result = gate.check_protocol_action(
        agent_role="vr_session",
        action_name="window.moved",
        arguments={"window_id": "win_1", "session_id": "sess_1"},
        required_scopes=["window.interact"],
    )

    assert result.is_allowed is True
    assert result.agent_role == "vr_session"


def test_destructive_or_unknown_vr_protocol_action_is_denied() -> None:
    gate = PermissionGate(DEFAULT_POLICIES)

    with pytest.raises(PermissionDenied):
        gate.check_protocol_action(
            agent_role="vr_session",
            action_name="window.closed",
            arguments={"window_id": "win_1"},
            required_scopes=["window.interact"],
        )

    with pytest.raises(PermissionDenied):
        gate.check_protocol_action(
            agent_role="vr_session",
            action_name="window.execute_arbitrary_code",
            arguments={},
            required_scopes=["window.interact"],
        )


def test_unknown_role_is_denied_by_default() -> None:
    gate = PermissionGate(DEFAULT_POLICIES)

    with pytest.raises(PermissionDenied):
        gate.check_protocol_action(
            agent_role="client_supplied_role",
            action_name="window.moved",
            arguments={},
            required_scopes=["window.interact"],
        )
