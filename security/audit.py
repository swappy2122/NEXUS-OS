"""Audit logging for NEXUS OS.

Every tool execution is recorded for accountability and debugging.
The AuditLog subscribes to ``tool.executed`` events on the EventBus
so that tool code never needs to import this module directly.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("NEXUS_OS.audit")


@dataclass
class AuditEntry:
    """A single recorded action."""

    timestamp: datetime
    agent_role: str
    tool_name: str
    arguments: dict[str, Any]
    success: bool
    error: str | None = None
    duration_ms: float = 0.0


class AuditLog:
    """In-memory audit log backed by an EventBus subscription.

    Parameters:
        event_bus: The application event bus to subscribe to.
        max_entries: Rolling window of entries kept in memory.
    """

    EVENT_TYPE = "tool.executed"

    def __init__(self, event_bus: EventBus, max_entries: int = 5000) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._event_bus = event_bus
        self._event_bus.subscribe(self.EVENT_TYPE, self._on_tool_executed)

    # -- event handler -----------------------------------------------------

    async def _on_tool_executed(self, data: dict[str, Any]) -> None:
        """Handle a ``tool.executed`` event from the bus."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            agent_role=data.get("agent_role", ""),
            tool_name=data.get("tool_name", ""),
            arguments=data.get("arguments", {}),
            success=data.get("success", False),
            error=data.get("error"),
            duration_ms=data.get("duration_ms", 0.0),
        )
        self._entries.append(entry)
        logger.info(
            "AUDIT | agent=%s tool=%s success=%s duration=%.1fms",
            entry.agent_role,
            entry.tool_name,
            entry.success,
            entry.duration_ms,
        )

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

    @property
    def total_entries(self) -> int:
        return len(self._entries)
