"""Agent framework types for NEXUS OS.

Defines the data contracts that flow through the agent layer:

* **Capability**      — what an agent can do (declarative)
* **AgentContext**     — everything an agent receives to process a request
* **AgentResult**      — standardised output from every agent execution
* **ToolCallRecord**   — audit entry for a single tool invocation
* **AgentError**       — base exception for agent-layer failures
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Capability(BaseModel):
    """Declares a specific ability of an agent.

    Capabilities are purely *descriptive* — they tell the Supervisor
    (and the user) what the agent can do, without coupling to specific
    tool implementations.

    Examples::

        Capability(name="file_read",  description="Read text files")
        Capability(name="shell_exec", description="Run shell commands")
    """

    name: str
    description: str = ""


class ToolCallRecord(BaseModel):
    """Immutable log entry for one tool invocation made during execution."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class AgentContext(BaseModel):
    """Input payload handed to :meth:`BaseAgent.execute`.

    The Supervisor (or any caller) builds this and the agent treats it
    as a read-only description of *what to do* and *what is known*.
    """

    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    session_id: str = "default"
    intent: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    system_state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Standardised response returned by every agent execution.

    * ``success`` + ``output`` for the happy path.
    * ``error`` for failures.
    * ``tool_calls_made`` for full auditability.
    * ``data`` for structured machine-readable payloads.
    """

    success: bool = True
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tool_calls_made: list[ToolCallRecord] = Field(default_factory=list)
    duration_ms: float = 0.0
    agent_name: str = ""


class AgentError(Exception):
    """Raised for expected agent-layer failures.

    Agents should raise this for *handled* errors (e.g. missing tool,
    no LLM configured).  Unhandled exceptions are caught by
    :meth:`BaseAgent.run` and wrapped in an ``AgentResult``.
    """

    def __init__(self, agent_name: str, message: str) -> None:
        self.agent_name = agent_name
        super().__init__(f"[{agent_name}] {message}")
