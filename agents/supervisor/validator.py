"""Action Validator for NEXUS Supervisor.

Validates structured actions produced by the LLM before execution:
1. Agent verification (agent must be registered)
2. Tool ownership (agent must own the requested tool)
3. Schema & argument validation (required parameters, types)
4. Path safety (blocks unauthorized access to restricted system directories)
5. Shell execution safety (enforces: The LLM must NOT receive unrestricted shell access)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agents.registry import AgentRegistry
from agents.supervisor.types import ActionValidationResult, StructuredAction

logger = logging.getLogger("nexus.supervisor.validator")

# Forbidden directories that tools must not access unless specifically authorized
RESTRICTED_SYSTEM_PATHS = [
    Path("/etc"),
    Path("/boot"),
    Path("/sys"),
    Path("/proc"),
    Path("/dev"),
    Path("/root"),
]

# Patterns representing unrestricted or destructive shell execution
FORBIDDEN_SHELL_PATTERNS = [
    # Recursive deletion on root or root subdirectories
    r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+[/~]",
    r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+\.\.",
    # Raw device writes and filesystem formatting
    r"\bdd\s+if=.*of=/dev/",
    r"\bmkfs(?:\.\w+)?\b",
    r"\bwipefs\b",
    # Fork bombs
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # Piping remote scripts directly into shell interpreters
    r"(?:curl|wget)\s+[^|]+\|\s*(?:ba|z|k|c)?sh",
    # Unrestricted sudo / su execution
    r"\bsudo\s+(?:rm|dd|mkfs|chmod\s+777\s+/)",
    r"\bsudo\s+-i\b",
    r"\bsu\s+-\b",
    # System shutdown or reboot attempts
    r"\b(?:shutdown|reboot|poweroff|init\s+0)\b",
]


class ActionValidator:
    """Validates structured actions prior to agent and tool execution.

    Ensures that every tool invocation strictly adheres to capability
    boundaries, schema contracts, path sandboxing, and shell execution policies.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def validate(self, action: StructuredAction) -> ActionValidationResult:
        """Validate a structured action against registry, schema, and security rules."""
        # 1. Agent Existence
        agent = self._registry.get(action.agent_name)
        if agent is None:
            return ActionValidationResult(
                is_valid=False,
                error=f"Validation failed: Unknown agent '{action.agent_name}'. "
                f"Available: {[a.name for a in self._registry]}",
            )

        # 2. Tool Ownership
        tool = agent.tools.get(action.tool_name)
        if tool is None:
            return ActionValidationResult(
                is_valid=False,
                error=f"Validation failed: Agent '{action.agent_name}' does not own tool '{action.tool_name}'. "
                f"Available tools: {list(agent.tools.keys())}",
            )

        # 3. Schema & Parameter Validation
        args = dict(action.arguments or {})

        # Friendly aliasing & defaults for common tool parameters
        if action.tool_name == "file_search":
            if "path" not in args and "root_dir" in args:
                args["path"] = args["root_dir"]
            elif "path" not in args:
                args["path"] = "."

        schema = tool.parameters_schema or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check required fields
        missing = [r for r in required if r not in args]
        if missing:
            return ActionValidationResult(
                is_valid=False,
                error=f"Validation failed: Tool '{action.tool_name}' missing required parameters: {missing}",
            )

        # Type checking for known arguments
        for param_name, param_val in args.items():
            param_meta = properties.get(param_name, {})
            expected_type = param_meta.get("type")
            if expected_type == "integer" and not isinstance(param_val, int):
                try:
                    args[param_name] = int(param_val)
                except (ValueError, TypeError):
                    return ActionValidationResult(
                        is_valid=False,
                        error=f"Validation failed: Parameter '{param_name}' must be an integer, got {param_val!r}",
                    )
            elif expected_type == "boolean" and not isinstance(param_val, bool):
                if str(param_val).lower() in ("true", "1"):
                    args[param_name] = True
                elif str(param_val).lower() in ("false", "0"):
                    args[param_name] = False
                else:
                    return ActionValidationResult(
                        is_valid=False,
                        error=f"Validation failed: Parameter '{param_name}' must be a boolean, got {param_val!r}",
                    )

        # 4. Shell Execution Safety (No Unrestricted Shell Access)
        if action.tool_name == "process_run":
            cmd = str(args.get("command", "")).strip()
            if not cmd:
                return ActionValidationResult(
                    is_valid=False,
                    error="Validation failed: Command cannot be empty for process_run",
                )

            for pattern in FORBIDDEN_SHELL_PATTERNS:
                if re.search(pattern, cmd, re.IGNORECASE):
                    logger.warning("Blocked dangerous shell pattern: %s in command: %s", pattern, cmd)
                    return ActionValidationResult(
                        is_valid=False,
                        error=f"Security violation: Unrestricted or destructive shell command blocked: '{cmd}'",
                    )

            # Clamp timeout to avoid hanging processes
            timeout = args.get("timeout", 30)
            if isinstance(timeout, (int, float)) and timeout > 60:
                args["timeout"] = 60

        # 5. Path Security Validation
        path_keys = ["path", "source", "destination", "root_dir"]
        for pk in path_keys:
            if pk in args and args[pk]:
                path_val = str(args[pk]).strip()
                if "\x00" in path_val:
                    return ActionValidationResult(
                        is_valid=False,
                        error="Security violation: Null bytes are not permitted in path",
                    )

                try:
                    p = Path(path_val).expanduser().resolve()
                    for denied in RESTRICTED_SYSTEM_PATHS:
                        if p == denied or denied in p.parents:
                            # Note: App tools or sysinfo tools may read /proc directly,
                            # but file agent operations (read, write, delete, move, mkdir) must NOT.
                            if action.agent_name == "file_agent":
                                return ActionValidationResult(
                                    is_valid=False,
                                    error=f"Security violation: Access to restricted system path '{p}' is forbidden",
                                )
                except Exception as exc:
                    return ActionValidationResult(
                        is_valid=False,
                        error=f"Validation failed: Invalid path specification: {exc}",
                    )

        return ActionValidationResult(
            is_valid=True,
            sanitized_arguments=args,
        )
