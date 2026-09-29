"""Pydantic request/response schemas for the NEXUS OS API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# -- Chat -----------------------------------------------------------------

class ChatRequest(BaseModel):
    """Incoming chat message from a frontend."""

    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    """Response to a chat request."""

    task_id: str
    status: str
    result: str = ""
    error: str | None = None
    agent_used: str = ""
    duration_ms: float = 0.0


# -- Agents ---------------------------------------------------------------

class AgentInfo(BaseModel):
    """Public info about a registered agent."""

    name: str
    role: str
    description: str


class AgentListResponse(BaseModel):
    agents: list[AgentInfo]


# -- Tools ----------------------------------------------------------------

class ToolInfo(BaseModel):
    """Public info about a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = []


class ToolListResponse(BaseModel):
    tools: list[ToolInfo]


# -- System ----------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    uptime_seconds: float = 0.0
    agents_count: int = 0
    tools_count: int = 0
    model_backends: dict[str, bool] = Field(default_factory=dict)


class ContextSnapshotResponse(BaseModel):
    session_id: str
    conversation_length: int = 0
    system_state: dict[str, Any] = Field(default_factory=dict)
