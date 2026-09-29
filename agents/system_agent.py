"""System monitoring agent for NEXUS OS.

Provides read-only system monitoring: CPU usage, memory metrics, disk space,
operating system details, and running process information.
Uses the LLM to interpret requests and plan tool calls.
Strictly avoids shutdown, reboot, privilege escalation, or destructive operations.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, Capability


SYSTEM_PROMPT = """\
You are the System Agent in NEXUS OS. Your job is to help the user monitor system health and metrics.

You have access to these read-only monitoring tools:
- system_info: Get complete system status snapshot (CPU, memory, disk, OS, processes)
- system_cpu: Get detailed CPU usage, architecture, core counts, and load averages
- system_memory: Get detailed RAM and swap memory usage
- system_disk: Get disk space usage for partitions
- system_os: Get OS name, kernel version, hostname, and uptime
- system_processes: Get read-only process count and running process summary

Guidelines:
- Always use read-only monitoring tools.
- Never attempt shutdown, reboot, privilege escalation, or system-altering commands.
- Present system metrics clearly with appropriate units (GB, %, load averages).
"""

SYSTEM_CAPABILITIES = [
    Capability(name="system_info", description="Report complete system status snapshot"),
    Capability(name="system_cpu", description="Report CPU usage, load averages, and architecture"),
    Capability(name="system_memory", description="Report RAM and swap memory usage"),
    Capability(name="system_disk", description="Report disk space usage and partition metrics"),
    Capability(name="system_os", description="Report operating system and kernel metadata"),
    Capability(name="system_processes", description="Report running process count and summary"),
]


class SystemAgent(BaseAgent):
    """Specialized agent for read-only system monitoring and diagnostics."""

    def __init__(self) -> None:
        super().__init__(
            name="system_agent",
            description="Provides read-only system monitoring: CPU, memory, disk, OS info, and process status.",
            capabilities=SYSTEM_CAPABILITIES,
        )

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Process a system monitoring query using LLM-guided tool selection or direct execution."""
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

        for msg in ctx.conversation_history[-5:]:
            messages.append(msg)

        messages.append({"role": "user", "content": ctx.intent})

        response = await self.think(messages)

        if response.tool_calls:
            for tc in response.tool_calls:
                await self.use_tool(tc["name"], **tc["arguments"])

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
                    "Tool results:\n"
                    + "\n".join(tool_output_parts)
                    + "\n\nSummarize the system metrics for the user."
                ),
            })
            summary = await self.think(messages, tools=[])
            return AgentResult(output=summary.content)

        return AgentResult(output=response.content)
