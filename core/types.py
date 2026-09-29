"""Shared types, enums, and data models for NEXUS OS.

Every module imports its common data structures from here to avoid
circular dependencies and keep a single source of truth for the
data contracts that flow between layers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    """Identifies the functional role of an agent."""

    SUPERVISOR = "supervisor"
    FILE = "file"
    SYSTEM = "system"
    CODE = "code"
    WEB = "web"
    APP = "app"
    WINDOW = "window"
    WORKSPACE = "workspace"
    VOICE = "voice"
    VISION = "vision"


class TaskStatus(str, Enum):
    """Lifecycle state of a task flowing through the agent layer."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Agent ↔ Agent messaging
# ---------------------------------------------------------------------------

class TaskMessage(BaseModel):
    """Message passed between Supervisor and Specialized Agents.

    The Supervisor creates one of these for each sub-task it delegates,
    and the specialized agent returns an updated copy with status and
    result fields populated.
    """

    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    session_id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    intent: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tool layer types
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """A request from an Agent to execute a Tool."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    calling_agent: str = ""


class ToolResult(BaseModel):
    """The structured result of a tool execution."""

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Model layer types
# ---------------------------------------------------------------------------

class ModelResponse(BaseModel):
    """Response returned by a model backend after inference."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    finish_reason: str = ""
