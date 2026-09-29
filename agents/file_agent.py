"""File operations agent for NEXUS OS.

Handles file-system tasks: searching files, retrieving metadata, opening files via OS,
creating directories, moving/renaming files, reading, writing, and deleting files.
Uses the LLM to interpret natural-language requests and plan tool calls.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, Capability


SYSTEM_PROMPT = """\
You are the File Agent in NEXUS OS. Your job is to help the user with file-system operations safely.

You have access to these tools:
- file_search: Search for files matching a glob pattern
- file_metadata: Retrieve detailed metadata (size, timestamps, permissions) for a file or directory
- file_open_os: Open a file or document using the OS default application
- file_mkdir: Create a new directory
- file_move: Move or rename a file or directory
- file_read: Read text file contents
- file_write: Create or write content to a file
- file_delete: Delete a file (requires user confirmation)

Guidelines:
- Always use safe filesystem operations.
- When searching, use appropriate glob patterns.
- When moving files, ensure destination path is clearly specified.
- Never attempt operations on restricted system directories (/etc, /boot, /sys, /proc, /dev).
- Always return clear, structured, and informative summaries of actions taken.
"""

FILE_CAPABILITIES = [
    Capability(name="file_search", description="Search for files by glob pattern"),
    Capability(name="file_metadata", description="Retrieve file/directory metadata"),
    Capability(name="file_open_os", description="Open a file using the OS default application"),
    Capability(name="file_mkdir", description="Create a directory"),
    Capability(name="file_move", description="Move or rename a file or directory"),
    Capability(name="file_read", description="Read text file contents"),
    Capability(name="file_write", description="Create or overwrite files"),
    Capability(name="file_delete", description="Delete files (with confirmation)"),
]


class FileAgent(BaseAgent):
    """Specialized agent for file system operations."""

    def __init__(self) -> None:
        super().__init__(
            name="file_agent",
            description="Handles file operations: search, metadata, open, mkdir, move, read, write, delete.",
            capabilities=FILE_CAPABILITIES,
        )

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Process a file-related task using LLM-guided tool selection or direct execution."""
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

        # Include conversation context if available
        for msg in ctx.conversation_history[-5:]:
            messages.append(msg)

        messages.append({"role": "user", "content": ctx.intent})

        # Ask the LLM what to do — it may request tool calls
        response = await self.think(messages)

        # If the model wants to call tools, execute them
        if response.tool_calls:
            for tc in response.tool_calls:
                await self.use_tool(tc["name"], **tc["arguments"])

            # Feed tool results back to the LLM for a summary
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
                    + "\n\nSummarize what happened for the user."
                ),
            })
            summary = await self.think(messages, tools=[])
            return AgentResult(output=summary.content)

        # Model responded directly without tool calls
        return AgentResult(output=response.content)
