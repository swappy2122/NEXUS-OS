"""Central tool registry for NEXUS OS.

The ``ToolRegistry`` is the single place where agents request tool
execution.  It handles:

1. **Registration** — tools register themselves at startup.
2. **Discovery** — agents ask for LLM-formatted schemas of their allowed
   tools.
3. **Permission-gated execution** — every ``execute()`` call is checked
   against the ``PermissionGate`` before the actual tool runs.
4. **Audit events** — publishes ``tool.executed`` on the EventBus so the
   audit log picks it up without coupling.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.event_bus import EventBus
from core.types import ToolCall, ToolResult
from security.permissions import PermissionDenied, PermissionGate
from tools.base import BaseTool

logger = logging.getLogger("NEXUS_OS.tools")


class ToolRegistry:
    """Manages tool lifecycle, discovery, and permission-gated execution.

    Parameters:
        security_gate: The :class:`PermissionGate` to enforce on every
            execution.
        event_bus: Optional event bus for audit event publishing.
    """

    def __init__(
        self,
        security_gate: PermissionGate,
        event_bus: EventBus | None = None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._security = security_gate
        self._event_bus = event_bus

    # -- registration ------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """Register a tool.  Overwrites any existing tool with the same name."""
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def unregister(self, tool_name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(tool_name, None)

    # -- discovery ---------------------------------------------------------

    def get_tool(self, name: str) -> BaseTool | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_schemas_for_agent(self, required_tools: list[str]) -> list[dict[str, Any]]:
        """Return LLM-formatted schemas for the specified tool names.

        Only tools that are actually registered are included (unknown
        names are silently skipped).
        """
        schemas = []
        for name in required_tools:
            tool = self._tools.get(name)
            if tool:
                schemas.append(tool.to_llm_schema())
        return schemas

    # -- execution ---------------------------------------------------------

    async def execute(self, call: ToolCall) -> ToolResult:
        """Execute a tool with permission checking and audit logging.

        Returns a ``ToolResult`` — never raises for expected failures.
        """
        # Deny-by-default for unknown tools
        tool = self._tools.get(call.tool_name)
        if tool is None:
            err_msg = f"[UNKNOWN_TOOL_DENIED][{call.calling_agent}][{call.tool_name}] Tool '{call.tool_name}' is unclassified or unregistered (denied by default)."
            if hasattr(self._security, "_log_and_emit"):
                self._security._log_and_emit(
                    agent_role=call.calling_agent,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    decision="deny",
                    error=err_msg,
                )
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error=err_msg,
            )

        # Permission and safety check
        try:
            if hasattr(self._security, "check_tool_async"):
                await self._security.check_tool_async(
                    agent_role=call.calling_agent,
                    tool_name=tool.name,
                    arguments=call.arguments,
                    required_scopes=tool.required_permissions,
                )
            else:
                self._security.check(
                    agent_role=call.calling_agent,
                    required_scopes=tool.required_permissions,
                    target_path=call.arguments.get("path"),
                )
        except (PermissionDenied, Exception) as exc:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error=str(exc),
            )

        # Execute with timing
        start = time.monotonic()
        try:
            result = await tool.execute(**call.arguments)
        except Exception as exc:
            logger.exception("Tool %s raised an unexpected error", call.tool_name)
            result = ToolResult(
                tool_name=call.tool_name,
                success=False,
                error=f"Internal tool error: {exc}",
            )

        result.duration_ms = (time.monotonic() - start) * 1000

        # Publish audit event
        if self._event_bus:
            category_val = getattr(tool.action_category, "value", str(tool.action_category)) if hasattr(tool, "action_category") else None
            risk_val = getattr(tool.risk_level, "value", str(tool.risk_level)) if hasattr(tool, "risk_level") else None
            await self._event_bus.publish(
                "tool.executed",
                {
                    "agent_role": call.calling_agent,
                    "tool_name": call.tool_name,
                    "arguments": call.arguments,
                    "success": result.success,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                    "action_category": category_val,
                    "risk_level": risk_val,
                },
            )

        return result
