"""Base tool abstract interface for NEXUS OS.

Every tool in the system subclasses ``BaseTool`` and provides:

* A JSON-schema description of its parameters (so LLMs can discover
  and call the tool via function-calling).
* A list of required permission scopes (checked by the ToolRegistry
  before execution).
* An async ``execute()`` method that does the actual work and returns
  a :class:`~core.types.ToolResult`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.types import ToolResult


class BaseTool(ABC):
    """Abstract Base Class for NEXUS OS Tools.

    Subclasses **must** set the class-level attributes ``name``,
    ``description``, ``parameters_schema``, and
    ``required_permissions``.  They must also implement ``execute()``.
    """

    # -- class-level metadata (override in subclasses) ---------------------
    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {}
    required_permissions: list[str] = []

    # -- LLM interop -------------------------------------------------------

    def to_llm_schema(self) -> dict[str, Any]:
        """Export this tool as a function-calling schema understood by LLMs.

        The returned dict follows the widely-adopted OpenAI function-calling
        format so that it works with Ollama, OpenAI, Anthropic, etc.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    # -- execution ---------------------------------------------------------

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments.

        Implementations must return a ``ToolResult`` — never raise on
        expected failures; instead return ``ToolResult(success=False,
        error="...")``.
        """
        ...

    # -- dunder ------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
