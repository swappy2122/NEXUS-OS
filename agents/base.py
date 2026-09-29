"""Reusable agent base class for NEXUS OS.

Design goals
────────────
1. **Self-contained metadata** — every agent carries its own name,
   description, and capability list.
2. **Tool ownership** — tools are registered *on* the agent, not
   looked up from a global registry.  The agent decides what it can use.
3. **Vendor-agnostic LLM hook** — LLM access is an *injected callable*
   behind :class:`LLMProvider`, not a hard import of any model library.
4. **Standard execution contract** — ``execute(AgentContext) → AgentResult``
   with a public ``run()`` wrapper that adds timing, error handling, and
   audit logging automatically.
5. **No unnecessary abstractions** — one ABC, one protocol, done.

Extending the framework
───────────────────────
To create a new agent, subclass :class:`BaseAgent`, set the class-level
metadata, and implement :meth:`execute`::

    class GreetAgent(BaseAgent):
        async def execute(self, ctx: AgentContext) -> AgentResult:
            return AgentResult(output=f"Hello from {self.name}!")
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Iterable, Protocol, runtime_checkable

from core.types import ModelResponse, ToolResult
from tools.base import BaseTool

from agents.types import (
    AgentContext,
    AgentError,
    AgentResult,
    Capability,
    ToolCallRecord,
)

# ── Sentinel for "argument not provided" ─────────────────────────────────
_UNSET: Any = object()


# ── LLM integration protocol ────────────────────────────────────────────

@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol that any LLM backend must satisfy.

    This keeps agents completely decoupled from Ollama, OpenAI, or any
    other vendor.  Any object whose ``chat`` method matches this
    signature can be injected via :meth:`BaseAgent.set_llm`.
    """

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse: ...


# ── Base Agent ───────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base class for every NEXUS OS agent.

    Attributes (set in subclasses or ``__init__``):
        name:         Unique agent identifier.
        description:  Human-readable purpose summary.
        capabilities: Declarative list of what the agent can do.
    """

    # ── metadata ─────────────────────────────────────────────────────────

    def __init__(
        self,
        name: str,
        description: str = "",
        capabilities: list[Capability] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.capabilities: list[Capability] = capabilities or []

        # Internal state
        self._tools: dict[str, BaseTool] = {}
        self._llm: LLMProvider | None = None
        self._tool_call_log: list[ToolCallRecord] = []
        self._logger = logging.getLogger(f"nexus.agent.{name}")

    # ── Tool management ──────────────────────────────────────────────────

    def register_tool(self, tool: BaseTool) -> None:
        """Add a tool to this agent's personal toolbox."""
        self._tools[tool.name] = tool
        self._logger.debug("Registered tool: %s", tool.name)

    def register_tools(self, tools: Iterable[BaseTool]) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register_tool(tool)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Read-only snapshot of registered tools (name → instance)."""
        return dict(self._tools)

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        """LLM-compatible function-calling schemas for all registered tools."""
        return [t.to_llm_schema() for t in self._tools.values()]

    # ── LLM integration ──────────────────────────────────────────────────

    def set_llm(self, provider: LLMProvider) -> None:
        """Inject an LLM provider.

        Can be swapped at runtime — useful for testing or model routing.
        """
        self._llm = provider
        self._logger.debug("LLM provider set: %s", type(provider).__name__)

    async def think(
        self,
        messages: list[dict[str, Any]],
        tools: Any = _UNSET,
        **kwargs: Any,
    ) -> ModelResponse:
        """Request LLM inference.

        Parameters:
            messages: Chat-style message list (role + content dicts).
            tools:    Tool schemas to pass. If omitted, this agent's
                      ``tool_schemas`` are used automatically.  Pass
                      an empty list ``[]`` to explicitly disable
                      function-calling.
            **kwargs: Forwarded to the LLM provider (temperature, …).

        Raises:
            AgentError: If no LLM provider has been set.
        """
        if self._llm is None:
            raise AgentError(self.name, "No LLM provider configured — call set_llm() first")

        resolved_tools = self.tool_schemas if tools is _UNSET else tools
        return await self._llm.chat(
            messages,
            tools=resolved_tools or None,
            **kwargs,
        )

    # ── Tool execution ───────────────────────────────────────────────────

    async def use_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a registered tool with automatic logging and recording.

        Every call is appended to the internal ``_tool_call_log`` so
        that :meth:`run` can include it in the :class:`AgentResult`.

        Raises:
            AgentError: If *tool_name* is not registered on this agent.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise AgentError(
                self.name,
                f"Tool not registered: '{tool_name}'. "
                f"Available: {list(self._tools.keys())}",
            )

        self._logger.info("Calling tool: %s(%s)", tool_name, _brief(kwargs))
        start = time.monotonic()

        try:
            result = await tool.execute(**kwargs)
        except Exception as exc:
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool raised: {exc}",
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        result.duration_ms = elapsed_ms

        # Record for audit trail
        self._tool_call_log.append(
            ToolCallRecord(
                tool_name=tool_name,
                arguments=kwargs,
                success=result.success,
                output=result.output,
                error=result.error,
                duration_ms=elapsed_ms,
            )
        )

        log_level = logging.INFO if result.success else logging.WARNING
        self._logger.log(
            log_level,
            "Tool %s → %s (%.1f ms)",
            tool_name,
            "OK" if result.success else f"FAIL: {result.error}",
            elapsed_ms,
        )
        return result

    # ── Execution contract ───────────────────────────────────────────────

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """Process a request.  **Subclasses implement this.**

        Implementations should:
        * Use ``self.use_tool(...)`` to interact with the OS.
        * Use ``self.think(...)`` to request LLM inference.
        * Return an ``AgentResult`` with ``success=True/False``.
        * Let unexpected exceptions propagate — ``run()`` catches them.
        """
        ...

    async def run(self, context: AgentContext) -> AgentResult:
        """Public entry point — wraps :meth:`execute` with:

        * Automatic timing (``duration_ms``).
        * Exception → ``AgentResult(success=False)`` conversion.
        * Tool-call log attachment.
        * Structured logging.

        Callers (Supervisor, API layer) should call ``run()`` instead
        of ``execute()`` directly.
        """
        self._tool_call_log.clear()
        self._logger.info("▶ Task %s: %.100s", context.task_id, context.intent)
        start = time.monotonic()

        try:
            result = await self.execute(context)
        except AgentError:
            raise  # expected errors bubble up
        except Exception as exc:
            self._logger.exception("Unhandled error in execute()")
            result = AgentResult(success=False, error=str(exc))

        # Attach metadata
        result.agent_name = self.name
        if not result.tool_calls_made:
            result.tool_calls_made = list(self._tool_call_log)

        self._logger.info(
            "◀ %s | %s | %.0f ms | %d tool call(s)",
            context.task_id,
            "OK" if result.success else "FAIL",
            result.duration_ms,
            len(result.tool_calls_made),
        )
        return result

    # ── Lifecycle hooks ──────────────────────────────────────────────────

    def on_start(self) -> None:
        """Called once when the agent system boots.  Override for setup."""
        self._logger.info("Agent started")

    def on_stop(self) -> None:
        """Called once on shutdown.  Override for cleanup."""
        self._logger.info("Agent stopped")

    # ── Introspection ────────────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        """Return a serialisable metadata snapshot for the API layer."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": [c.model_dump() for c in self.capabilities],
            "tools": list(self._tools.keys()),
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ── helpers ──────────────────────────────────────────────────────────────

def _brief(d: dict, max_len: int = 80) -> str:
    """Compact dict preview for log messages."""
    s = ", ".join(f"{k}={v!r}" for k, v in d.items())
    return s[:max_len] + "…" if len(s) > max_len else s
