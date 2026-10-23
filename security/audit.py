"""Audit logging and security event tracking for NEXUS OS.

Every security check, confirmation request, denial, and tool execution
is recorded for accountability, defensive forensics, and debugging.
Subscribes to ``tool.executed`` and ``security.*`` events on the EventBus.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("NEXUS_OS.audit")

# Keys whose values should be masked in arguments for security logs
SENSITIVE_ARG_KEYS = {"password", "secret", "token", "auth", "api_key", "credential"}


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy of tool arguments with credentials masked."""
    sanitized: dict[str, Any] = {}
    for k, v in args.items():
        if any(secret_key in k.lower() for secret_key in SENSITIVE_ARG_KEYS):
            sanitized[k] = "******"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_args(v)
        else:
            sanitized[k] = v
    return sanitized


@dataclass
class AuditEntry:
    """A single recorded action or security evaluation."""

    timestamp: datetime
    agent_role: str
    tool_name: str
    arguments: dict[str, Any]
    success: bool
    error: str | None = None
    duration_ms: float = 0.0
    action_category: str | None = None
    risk_level: str | None = None
    decision: str = "allow"
    event_type: str = "tool.executed"

    def to_dict(self) -> dict[str, Any]:
        """Convert audit entry to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "agent_role": self.agent_role,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "action_category": self.action_category,
            "risk_level": self.risk_level,
            "decision": self.decision,
        }


class AuditLog:
    """In-memory security and execution audit log.

    Parameters:
        event_bus: The application event bus to subscribe to (optional).
        max_entries: Rolling window of entries kept in memory.
    """

    EVENT_TYPES = [
        "tool.executed",
    ]

    def __init__(self, event_bus: EventBus | None = None, max_entries: int = 5000) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._event_bus = event_bus
        if self._event_bus:
            for ev_type in self.EVENT_TYPES:
                self._event_bus.subscribe(ev_type, self._on_event)

    # -- event handlers ----------------------------------------------------

    async def _on_event(self, data: dict[str, Any]) -> None:
        """Handle incoming event from event bus."""
        event_type = data.get("event_type", "tool.executed")
        if "success" in data and "decision" not in data:
            decision = "allow" if data.get("success") else "deny"
        else:
            decision = data.get("decision", "allow")

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            agent_role=data.get("agent_role", "unknown"),
            tool_name=data.get("tool_name", "unknown"),
            arguments=_sanitize_args(data.get("arguments", {})),
            success=bool(data.get("success", False)),
            error=data.get("error"),
            duration_ms=float(data.get("duration_ms", 0.0)),
            action_category=data.get("action_category"),
            risk_level=data.get("risk_level"),
            decision=decision,
        )
        self.record(entry)

    def record(self, entry: AuditEntry) -> None:
        """Record an entry directly into the audit log."""
        self._entries.append(entry)
        level = logging.INFO if entry.success and entry.decision == "allow" else logging.WARNING
        logger.log(
            level,
            "AUDIT | event=%s agent=%s tool=%s decision=%s risk=%s success=%s (%.1fms)",
            entry.event_type,
            entry.agent_role,
            entry.tool_name,
            entry.decision,
            entry.risk_level,
            entry.success,
            entry.duration_ms,
        )

    def record_security_decision(
        self,
        agent_role: str,
        tool_name: str,
        arguments: dict[str, Any],
        decision: str,
        action_category: str | None = None,
        risk_level: str | None = None,
        error: str | None = None,
    ) -> AuditEntry:
        """Directly record a security check outcome."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            event_type="security.check",
            agent_role=agent_role,
            tool_name=tool_name,
            arguments=_sanitize_args(arguments),
            success=(decision == "allow"),
            error=error,
            action_category=action_category,
            risk_level=risk_level,
            decision=decision,
        )
        self.record(entry)
        return entry

    # -- query API ---------------------------------------------------------

    def get_history(
        self,
        agent_role: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Return recent audit entries, optionally filtered by agent role."""
        entries = list(self._entries)
        if agent_role:
            entries = [e for e in entries if e.agent_role == agent_role]
        return entries[-limit:]

    def get_security_events(
        self,
        agent_role: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        action_category: str | None = None,
        decision: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Filter audit log entries by multiple security dimensions."""
        results = list(self._entries)
        if agent_role:
            results = [e for e in results if e.agent_role == agent_role]
        if tool_name:
            results = [e for e in results if e.tool_name == tool_name]
        if risk_level:
            results = [e for e in results if e.risk_level == risk_level]
        if action_category:
            results = [e for e in results if e.action_category == action_category]
        if decision:
            results = [e for e in results if e.decision == decision]
        return results[-limit:]

    def get_denied_events(self, limit: int = 100) -> list[AuditEntry]:
        """Return recent events where access or execution was denied."""
        return self.get_security_events(decision="deny", limit=limit)

    def get_summary(self) -> dict[str, Any]:
        """Return aggregated statistics of audit history."""
        total = len(self._entries)
        allowed = sum(1 for e in self._entries if e.decision == "allow")
        denied = sum(1 for e in self._entries if e.decision == "deny")
        confirmations = sum(1 for e in self._entries if e.decision == "require_confirmation")
        high_risk = sum(1 for e in self._entries if e.risk_level in ("high", "critical"))

        return {
            "total_entries": total,
            "allowed_count": allowed,
            "denied_count": denied,
            "confirmation_requests": confirmations,
            "high_risk_actions": high_risk,
        }

    @property
    def total_entries(self) -> int:
        return len(self._entries)
