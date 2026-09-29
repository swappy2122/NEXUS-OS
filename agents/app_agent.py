"""Application agent for NEXUS OS.

Handles application management tasks: listing installed applications, listing running
processes/apps, launching desktop applications, and closing/terminating apps.
Uses the LLM to interpret natural language requests and plan tool calls.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, Capability


SYSTEM_PROMPT = """\
You are the App Agent in NEXUS OS. Your job is to help the user manage desktop applications and system locations on their host machine.

You have access to these tools:
- app_list_installed: List installed desktop applications on the system
- app_list_running: List currently running applications and user processes
- app_is_running: Check whether a specific application or process is active
- app_open: Launch/open an application (e.g. "firefox") or system folder (Files, File Manager, Downloads, Documents, Home)
- app_close: Close/terminate a running application by name or PID (requires user confirmation)

Guidelines:
- If asked to list installed software or applications, call `app_list_installed`.
- If asked to check what applications or processes are currently running, call `app_list_running`.
- If asked to check whether an app is running, call `app_is_running`.
- If asked to open/launch an application (e.g. "open firefox", "launch vlc") or open the file manager / folders (e.g. "open files", "open file manager", "open downloads", "open documents", "open home"), call `app_open`.
- If asked to close/kill/quit an application (e.g. "close chrome", "kill pid 1234"), call `app_close`.
- Always return clear success or error results summarizing the actions taken and outcome.
"""

APP_CAPABILITIES = [
    Capability(name="app_list", description="List installed and running desktop applications"),
    Capability(name="app_open", description="Launch/open desktop applications"),
    Capability(name="app_close", description="Close/terminate running applications (with confirmation)"),
]


class AppAgent(BaseAgent):
    """Specialized agent for desktop application lifecycle management."""

    def __init__(self) -> None:
        super().__init__(
            name="app_agent",
            description="Manages desktop applications: list installed/running apps, launch apps, and close apps.",
            capabilities=APP_CAPABILITIES,
        )

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Process an application management task using LLM-guided tool selection or direct execution."""
        # Direct execution path: structured action already planned and validated by Supervisor
        tool_name = ctx.parameters.get("tool_name")
        if tool_name:
            args = ctx.parameters.get("arguments", {})
            res = await self.use_tool(tool_name, **args)
            return AgentResult(
                success=res.success,
                output=str(res.output) if res.success else "",
                error=res.error,
                data={"direct_execution": True},
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        # Include recent conversation history if provided
        for msg in ctx.conversation_history[-5:]:
            messages.append(msg)

        messages.append({"role": "user", "content": ctx.intent})

        # Ask the LLM to plan and decide tool calls
        response = await self.think(messages)

        # If the LLM requested tool execution, execute each tool
        if response.tool_calls:
            for tc in response.tool_calls:
                await self.use_tool(tc["name"], **tc["arguments"])

            # Format tool call outcomes for final summary
            tool_output_parts = []
            for rec in self._tool_call_log:
                status = "✓" if rec.success else "✗"
                output_preview = str(rec.output or rec.error)[:500]
                tool_output_parts.append(
                    f"[{status}] {rec.tool_name}: {output_preview}"
                )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": (
                    "Tool execution results:\n"
                    + "\n".join(tool_output_parts)
                    + "\n\nSummarize the outcome clearly for the user."
                ),
            })
            summary = await self.think(messages, tools=[])
            return AgentResult(
                output=summary.content,
                data={"tool_calls": len(self._tool_call_log)},
            )

        # Model responded directly without calling tools
        return AgentResult(output=response.content)
