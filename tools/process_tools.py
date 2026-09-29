"""Process / shell-command tools for NEXUS OS.

Allows agents to run shell commands in a controlled manner.
Execution is subject to permission gating (``process.execute`` scope)
and typically requires user confirmation per the default policy.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from core.types import ToolResult
from tools.base import BaseTool


class ProcessRunTool(BaseTool):
    """Run a shell command and return its stdout/stderr."""

    name = "process_run"
    description = (
        "Run a shell command on the host system and return its output. "
        "Dangerous operations require user confirmation."
    )
    required_permissions = ["process.execute"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30).",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command.",
            },
        },
        "required": ["command"],
    }

    # Maximum output bytes captured per stream to avoid memory issues.
    MAX_OUTPUT_BYTES = 50_000

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 30)
        cwd = kwargs.get("cwd")

        if not command.strip():
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="Empty command",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            stdout = stdout_bytes.decode(errors="replace")[: self.MAX_OUTPUT_BYTES]
            stderr = stderr_bytes.decode(errors="replace")[: self.MAX_OUTPUT_BYTES]

            success = proc.returncode == 0
            output = stdout if success else f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"

            return ToolResult(
                tool_name=self.name,
                success=success,
                output=output,
                error=stderr if not success else None,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )
