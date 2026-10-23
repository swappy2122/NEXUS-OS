"""Structured security exceptions for NEXUS OS.

All security exceptions inherit from ``SecurityError`` and provide structured
metadata (error code, agent role, tool name, detail, and violation category)
for audit logs, error reporting, and defensive debugging.
"""

from __future__ import annotations

from typing import Any


class SecurityError(Exception):
    """Base class for all security and permission violations in NEXUS OS."""

    def __init__(
        self,
        agent_role: str = "unknown",
        detail: str = "Security violation",
        code: str = "SECURITY_VIOLATION",
        tool_name: str | None = None,
        risk_level: str | None = None,
        action_category: str | None = None,
    ) -> None:
        self.agent_role = agent_role
        self.detail = detail
        self.code = code
        self.tool_name = tool_name
        self.risk_level = risk_level
        self.action_category = action_category

        prefix = f"[{self.code}][{self.agent_role}]"
        if tool_name:
            prefix += f"[{tool_name}]"
        super().__init__(f"{prefix} {self.detail}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize error details for APIs or audit logging."""
        return {
            "error_type": self.__class__.__name__,
            "code": self.code,
            "agent_role": self.agent_role,
            "tool_name": self.tool_name,
            "detail": self.detail,
            "risk_level": self.risk_level,
            "action_category": self.action_category,
        }


class PermissionDenied(SecurityError):
    """Raised when an agent attempts an action it is not authorized for.

    Maintains backward compatibility with legacy ``PermissionDenied(agent_role, detail)``.
    """

    def __init__(
        self,
        agent_role: str,
        detail: str,
        tool_name: str | None = None,
        code: str = "PERMISSION_DENIED",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            agent_role=agent_role,
            detail=detail,
            code=code,
            tool_name=tool_name,
            **kwargs,
        )


class UnknownToolError(SecurityError):
    """Raised when an unrecognized tool is invoked (deny-by-default enforcement)."""

    def __init__(
        self,
        agent_role: str,
        tool_name: str,
        detail: str | None = None,
    ) -> None:
        msg = detail or f"Tool '{tool_name}' is unclassified or unregistered (denied by default)."
        super().__init__(
            agent_role=agent_role,
            detail=msg,
            code="UNKNOWN_TOOL_DENIED",
            tool_name=tool_name,
        )


class PrivilegeEscalationError(SecurityError):
    """Raised when an agent attempts to escalate its privileges or bypass policy constraints."""

    def __init__(
        self,
        agent_role: str,
        detail: str,
        tool_name: str | None = None,
        escalation_vector: str = "scope_bypass",
    ) -> None:
        self.escalation_vector = escalation_vector
        super().__init__(
            agent_role=agent_role,
            detail=f"Privilege escalation attempt ({escalation_vector}): {detail}",
            code="PRIVILEGE_ESCALATION_BLOCKED",
            tool_name=tool_name,
        )


class RestrictedPathError(SecurityError):
    """Raised when an agent attempts to access restricted system directories or escapes sandbox."""

    def __init__(
        self,
        agent_role: str,
        path: str,
        detail: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        self.path = path
        msg = detail or f"Access to restricted or protected filesystem path '{path}' is forbidden."
        super().__init__(
            agent_role=agent_role,
            detail=msg,
            code="RESTRICTED_PATH_BLOCKED",
            tool_name=tool_name,
        )


class DangerousCommandError(SecurityError):
    """Raised when an unrestricted, dangerous, or privilege-escalating shell command is detected."""

    def __init__(
        self,
        agent_role: str,
        command: str,
        detail: str | None = None,
        pattern: str | None = None,
    ) -> None:
        self.command = command
        self.pattern = pattern
        msg = detail or f"Dangerous or unauthorized shell command blocked: '{command}'"
        super().__init__(
            agent_role=agent_role,
            detail=msg,
            code="DANGEROUS_COMMAND_BLOCKED",
            tool_name="process_run",
        )


class ConfirmationRequiredError(SecurityError):
    """Raised when an action requires explicit user confirmation before execution."""

    def __init__(
        self,
        agent_role: str,
        tool_name: str,
        request_id: str | None = None,
        detail: str | None = None,
        risk_level: str | None = None,
        action_category: str | None = None,
    ) -> None:
        self.request_id = request_id
        msg = detail or (
            f"Explicit user confirmation is required for {action_category or 'sensitive'} "
            f"tool '{tool_name}' (risk: {risk_level or 'medium/high'})."
        )
        super().__init__(
            agent_role=agent_role,
            detail=msg,
            code="USER_CONFIRMATION_REQUIRED",
            tool_name=tool_name,
            risk_level=risk_level,
            action_category=action_category,
        )


class ConfirmationRejectedError(SecurityError):
    """Raised when the user explicitly rejects confirmation for an action."""

    def __init__(
        self,
        agent_role: str,
        tool_name: str,
        detail: str | None = None,
    ) -> None:
        msg = detail or f"User rejected execution of tool '{tool_name}'."
        super().__init__(
            agent_role=agent_role,
            detail=msg,
            code="USER_CONFIRMATION_REJECTED",
            tool_name=tool_name,
        )
