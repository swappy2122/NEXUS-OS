"""Permission gate and security enforcement for NEXUS OS.

The ``PermissionGate`` sits between agents and the tool layer. Every tool
execution must pass through this gate before the tool's ``execute()`` method runs.

Key responsibilities:
1. Tool-level permission & scope verification
2. Deny-by-default for unknown tools or unconfigured agents
3. Privilege escalation defense (path traversal, symlink escapes, shell injection)
4. User confirmation for sensitive and destructive actions
5. Security audit logging & event emission
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from security.audit import AuditLog
from security.confirmation import (
    AutoApproveConfirmation,
    ConfirmationProvider,
    ConfirmationRequest,
)
from security.exceptions import (
    ConfirmationRejectedError,
    ConfirmationRequiredError,
    DangerousCommandError,
    PermissionDenied,
    PrivilegeEscalationError,
    RestrictedPathError,
    SecurityError,
    UnknownToolError,
)
from security.models import (
    ActionCategory,
    RiskLevel,
    SecurityCheckResult,
    SecurityDecision,
    classify_tool,
)
from security.policy import Policy

logger = logging.getLogger("NEXUS_OS.security")

# Destructive and privilege escalation patterns for shell commands
FORBIDDEN_COMMAND_PATTERNS = [
    # Privilege escalation via sudo or su
    (r"\bsudo\b", "Unrestricted sudo privilege escalation attempt"),
    (r"\bsu(?:\s+-|\s+\w+)?\b", "Direct superuser switch attempt"),
    # Recursive deletion of root or home directories
    (r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+[/~]", "Destructive root/home recursive deletion attempt"),
    (r"rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+\.\.", "Directory escape deletion attempt"),
    # Raw block device writes and filesystem formatting
    (r"\bdd\s+if=.*of=/dev/", "Raw block device overwriting attempt"),
    (r"\bmkfs(?:\.\w+)?\b", "Filesystem format command detected"),
    (r"\bwipefs\b", "Filesystem wipe command detected"),
    # SUID / permissions tampering for privilege escalation
    (r"\bchmod\s+(?:[0-7]*[4-7][0-7]{2}\s+|[ugo]*\+s\b)", "SUID/SGID privilege escalation attempt"),
    (r"\bchmod\s+(?:-R\s+)?777\s+[/~]", "Dangerous global write permission escalation"),
    # Modifying system security credential files
    (r"(?:>>?|tee\s+(?:-a\s+)?)\s*/etc/(?:passwd|shadow|sudoers)", "System credential file modification"),
    # Fork bombs
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "Denial-of-service fork bomb detected"),
    # Piping remote scripts directly into shell interpreters
    (r"(?:curl|wget)\s+[^|]+\|\s*(?:ba|z|k|c)?sh\b", "Remote uninspected script piping into shell"),
    # System shutdown or reboot commands
    (r"\b(?:shutdown|reboot|poweroff|init\s+0)\b", "System shutdown/reboot command blocked"),
]

# Standard restricted system paths
DEFAULT_RESTRICTED_PATHS = [
    Path("/etc"),
    Path("/boot"),
    Path("/sys"),
    Path("/proc"),
    Path("/dev"),
    Path("/root"),
]


class PermissionGate:
    """Enforces per-agent security and permission policies.

    Parameters:
        policies: Mapping of ``agent_role`` → :class:`Policy`.
        confirmation_provider: Provider for user confirmation (optional).
        audit_log: AuditLog instance to record security decisions (optional).
        event_bus: EventBus instance for event publishing (optional).
    """

    def __init__(
        self,
        policies: dict[str, Policy],
        confirmation_provider: ConfirmationProvider | None = None,
        audit_log: AuditLog | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._policies = policies
        self._confirmation_provider = confirmation_provider
        self._audit_log = audit_log
        self._event_bus = event_bus
        self._tool_classifications: dict[str, tuple[ActionCategory, RiskLevel]] = {}

    def set_confirmation_provider(self, provider: ConfirmationProvider) -> None:
        """Configure or replace the confirmation provider."""
        self._confirmation_provider = provider

    def set_audit_log(self, audit_log: AuditLog) -> None:
        """Configure or replace the audit log."""
        self._audit_log = audit_log

    def set_event_bus(self, event_bus: EventBus) -> None:
        """Configure or replace the event bus."""
        self._event_bus = event_bus

    def register_tool_classification(
        self,
        tool_name: str,
        category: ActionCategory,
        risk: RiskLevel,
    ) -> None:
        """Register custom risk classification for a tool."""
        self._tool_classifications[tool_name] = (category, risk)

    # -- Resolution helpers ------------------------------------------------

    def _resolve_policy(self, agent_role: str) -> Policy | None:
        """Lookup policy for an agent role, with automatic prefix/alias handling."""
        if agent_role in self._policies:
            return self._policies[agent_role]

        # Try stripping '_agent' or adding '_agent'
        if agent_role.endswith("_agent"):
            base = agent_role[:-6]
            if base in self._policies:
                return self._policies[base]
        else:
            cand = f"{agent_role}_agent"
            if cand in self._policies:
                return self._policies[cand]

        return None

    def get_tool_classification(
        self,
        tool_name: str,
        required_scopes: list[str] | None = None,
    ) -> tuple[ActionCategory, RiskLevel] | None:
        """Determine category and risk level for a tool."""
        if tool_name in self._tool_classifications:
            return self._tool_classifications[tool_name]
        return classify_tool(tool_name, required_scopes)

    # -- Legacy check method (Backward Compatibility) ----------------------

    def check(
        self,
        agent_role: str,
        required_scopes: list[str],
        target_path: str | None = None,
    ) -> bool:
        """Return ``True`` if *agent_role* holds all *required_scopes*.

        Maintains full backward compatibility with original signature and exceptions.
        """
        policy = self._resolve_policy(agent_role)
        if policy is None:
            raise PermissionDenied(agent_role, "No policy defined for this role")

        # Scope check
        missing = set(required_scopes) - policy.allowed_scopes
        if missing:
            raise PermissionDenied(
                agent_role,
                f"Missing scopes: {', '.join(sorted(missing))}",
            )

        # Path check
        if target_path:
            self._verify_path_safety(agent_role, target_path, policy.denied_paths)

        return True

    # -- Comprehensive Tool-Level Permission Check -------------------------

    async def check_tool_async(
        self,
        agent_role: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
        auto_confirm: bool = False,
    ) -> SecurityCheckResult:
        """Evaluate tool execution request asynchronously, prompting user if confirmation required."""
        args = arguments or {}
        policy = self._resolve_policy(agent_role)

        # 1. Unknown Agent Check (Deny-by-default)
        if policy is None:
            err = PermissionDenied(agent_role, "No policy defined for this role")
            self._log_and_emit(agent_role, tool_name, args, "deny", error=str(err))
            raise err

        # 2. Tool Classification & Deny-by-default for Unknown Tools
        classification = self.get_tool_classification(tool_name, required_scopes)
        if classification is None:
            err = UnknownToolError(agent_role, tool_name)
            self._log_and_emit(agent_role, tool_name, args, "deny", error=str(err))
            raise err

        category, risk = classification

        # 3. Shell Execution Privilege Check (Immediate privilege escalation block)
        if tool_name == "process_run" or (
            required_scopes and "process.execute" in required_scopes
        ):
            if not policy.allow_shell:
                err = PrivilegeEscalationError(
                    agent_role=agent_role,
                    detail="Shell command execution is prohibited for this role.",
                    tool_name="process_run",
                    escalation_vector="shell_execution_disabled",
                )
                self._log_and_emit(agent_role, tool_name, args, "deny", category, risk, str(err))
                raise err

        # 4. Scope Authorization Check
        if required_scopes:
            missing = set(required_scopes) - policy.allowed_scopes
            if missing:
                err = PermissionDenied(
                    agent_role,
                    f"Missing scopes: {', '.join(sorted(missing))}",
                    tool_name=tool_name,
                )
                self._log_and_emit(
                    agent_role, tool_name, args, "deny", category, risk, str(err)
                )
                raise err

        # 5. Explicit Tool Allowlist Check (if policy restricts specific tools)
        if policy.allowed_tools is not None and tool_name not in policy.allowed_tools:
            err = PermissionDenied(
                agent_role,
                f"Tool '{tool_name}' is not permitted by policy for role '{agent_role}'.",
                tool_name=tool_name,
            )
            self._log_and_emit(
                agent_role, tool_name, args, "deny", category, risk, str(err)
            )
            raise err

        # 6. Risk Ceiling Enforcement (No Privilege Escalation)
        if risk > policy.max_risk_level:
            err = PrivilegeEscalationError(
                agent_role=agent_role,
                detail=(
                    f"Action risk '{risk.value}' exceeds maximum permitted "
                    f"risk level '{policy.max_risk_level.value}' for role '{agent_role}'."
                ),
                tool_name=tool_name,
                escalation_vector="risk_level_exceeded",
            )
            self._log_and_emit(
                agent_role, tool_name, args, "deny", category, risk, str(err)
            )
            raise err

        # 7. Path Safety & Traversal Escapes Inspection
        try:
            self._check_argument_paths(agent_role, tool_name, args, policy.denied_paths)
        except SecurityError as err:
            self._log_and_emit(agent_role, tool_name, args, "deny", category, risk, str(err))
            raise

        # 8. Shell Command Safety & Privilege Escalation Inspection
        if tool_name == "process_run" or (
            required_scopes and "process.execute" in required_scopes
        ):
            try:
                self._check_shell_command(agent_role, args, policy)
            except SecurityError as err:
                self._log_and_emit(agent_role, tool_name, args, "deny", category, risk, str(err))
                raise

        # 8. User Confirmation Evaluation for Sensitive / Destructive Actions
        needs_confirm = self.needs_confirmation(
            agent_role=agent_role,
            required_scopes=required_scopes,
            tool_name=tool_name,
            category=category,
            risk=risk,
        )

        if needs_confirm and not auto_confirm:
            if self._confirmation_provider is None:
                err = ConfirmationRequiredError(
                    agent_role=agent_role,
                    tool_name=tool_name,
                    risk_level=risk.value,
                    action_category=category.value,
                )
                self._log_and_emit(
                    agent_role, tool_name, args, "require_confirmation", category, risk, str(err)
                )
                raise err

            req = ConfirmationRequest(
                agent_role=agent_role,
                tool_name=tool_name,
                arguments=args,
                action_category=category,
                risk_level=risk,
                reason=f"Action requires confirmation: {category.value} / {risk.value}",
            )

            # Publish confirmation request event
            if self._event_bus:
                await self._event_bus.publish(
                    "security.confirmation",
                    {"event_type": "security.confirmation", **req.to_dict()},
                )

            confirmed = await self._confirmation_provider.request_confirmation(req)
            if not confirmed:
                err = ConfirmationRejectedError(
                    agent_role=agent_role,
                    tool_name=tool_name,
                    detail=f"Execution of '{tool_name}' rejected by confirmation provider.",
                )
                self._log_and_emit(
                    agent_role, tool_name, args, "deny", category, risk, str(err)
                )
                raise err

        # Passed all security checks
        result = SecurityCheckResult(
            decision=SecurityDecision.ALLOW,
            reason="Authorized by policy",
            agent_role=agent_role,
            tool_name=tool_name,
            action_category=category,
            risk_level=risk,
            confirmation_required=needs_confirm,
            sanitized_arguments=args,
        )
        self._log_and_emit(agent_role, tool_name, args, "allow", category, risk)
        return result

    def check_tool_sync(
        self,
        agent_role: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
    ) -> SecurityCheckResult:
        """Synchronous version of check_tool (rejects if confirmation is needed and cannot be prompt)."""
        args = arguments or {}
        policy = self._resolve_policy(agent_role)

        if policy is None:
            raise PermissionDenied(agent_role, "No policy defined for this role")

        classification = self.get_tool_classification(tool_name, required_scopes)
        if classification is None:
            raise UnknownToolError(agent_role, tool_name)

        category, risk = classification

        if policy.allowed_tools is not None and tool_name not in policy.allowed_tools:
            raise PermissionDenied(
                agent_role,
                f"Tool '{tool_name}' is not permitted by policy for role '{agent_role}'.",
                tool_name=tool_name,
            )

        if required_scopes:
            missing = set(required_scopes) - policy.allowed_scopes
            if missing:
                raise PermissionDenied(
                    agent_role,
                    f"Missing scopes: {', '.join(sorted(missing))}",
                    tool_name=tool_name,
                )

        if risk > policy.max_risk_level:
            raise PrivilegeEscalationError(
                agent_role=agent_role,
                detail=f"Action risk '{risk.value}' exceeds policy maximum '{policy.max_risk_level.value}'.",
                tool_name=tool_name,
            )

        self._check_argument_paths(agent_role, tool_name, args, policy.denied_paths)

        if tool_name == "process_run" or (
            required_scopes and "process.execute" in required_scopes
        ):
            self._check_shell_command(agent_role, args, policy)

        needs_confirm = self.needs_confirmation(
            agent_role=agent_role,
            required_scopes=required_scopes,
            tool_name=tool_name,
            category=category,
            risk=risk,
        )

        if needs_confirm:
            if isinstance(self._confirmation_provider, AutoApproveConfirmation):
                pass
            else:
                raise ConfirmationRequiredError(
                    agent_role=agent_role,
                    tool_name=tool_name,
                    risk_level=risk.value,
                    action_category=category.value,
                )

        return SecurityCheckResult(
            decision=SecurityDecision.ALLOW,
            reason="Authorized by policy",
            agent_role=agent_role,
            tool_name=tool_name,
            action_category=category,
            risk_level=risk,
            confirmation_required=needs_confirm,
            sanitized_arguments=args,
        )

    def check_protocol_action(
        self,
        agent_role: str,
        action_name: str,
        arguments: dict[str, Any] | None = None,
        required_scopes: list[str] | None = None,
    ) -> SecurityCheckResult:
        """Authorize a non-tool protocol action at its dispatch boundary.

        Protocol actions use the same policy, classification, and audit
        machinery as tools. Unknown actions are denied by default.
        """
        args = arguments or {}
        if not args.get("session_id"):
            raise PermissionDenied(
                agent_role,
                "Validated session identity is required for protocol actions",
                tool_name=action_name,
            )
        return self.check_tool_sync(
            agent_role=agent_role,
            tool_name=action_name,
            arguments=args,
            required_scopes=required_scopes,
        )

    # -- Path and Command Security Verification ----------------------------

    def _verify_path_safety(
        self,
        agent_role: str,
        path_str: str,
        denied_paths: list[str],
        tool_name: str | None = None,
    ) -> None:
        """Inspect a filesystem path for directory traversal or access to restricted locations."""
        if not path_str or not str(path_str).strip():
            return

        clean_path = str(path_str).strip()
        if "\x00" in clean_path:
            raise PrivilegeEscalationError(
                agent_role=agent_role,
                detail="Null-byte injection detected in path argument.",
                tool_name=tool_name,
                escalation_vector="null_byte_injection",
            )

        try:
            # Resolve canonical path to defeat traversal (e.g. /tmp/../etc/passwd)
            resolved = Path(clean_path).expanduser().resolve()
        except Exception as exc:
            raise RestrictedPathError(
                agent_role=agent_role,
                path=clean_path,
                detail=f"Invalid path format: {exc}",
                tool_name=tool_name,
            )

        for denied in denied_paths:
            denied_resolved = Path(denied).expanduser().resolve()
            if resolved == denied_resolved or denied_resolved in resolved.parents:
                raise RestrictedPathError(
                    agent_role=agent_role,
                    path=clean_path,
                    detail=f"Access to restricted path '{resolved}' is denied by policy.",
                    tool_name=tool_name,
                )

    def _check_argument_paths(
        self,
        agent_role: str,
        tool_name: str,
        args: dict[str, Any],
        denied_paths: list[str],
    ) -> None:
        """Scan all known path argument keys in tool parameters."""
        path_keys = ["path", "src_path", "dst_path", "source", "destination", "root_dir", "cwd"]
        for key in path_keys:
            if key in args and args[key]:
                self._verify_path_safety(agent_role, str(args[key]), denied_paths, tool_name)

    def _check_shell_command(
        self,
        agent_role: str,
        args: dict[str, Any],
        policy: Policy,
    ) -> None:
        """Inspect shell commands for privilege escalation and destructive operations."""
        if not policy.allow_shell:
            raise PrivilegeEscalationError(
                agent_role=agent_role,
                detail="Shell command execution is prohibited for this role.",
                tool_name="process_run",
                escalation_vector="shell_execution_disabled",
            )

        cmd = str(args.get("command", "")).strip()
        if not cmd:
            return

        for pattern, reason in FORBIDDEN_COMMAND_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                logger.warning(
                    "Blocked forbidden command pattern (%s): '%s' by agent '%s'",
                    reason,
                    cmd,
                    agent_role,
                )
                raise DangerousCommandError(
                    agent_role=agent_role,
                    command=cmd,
                    detail=f"{reason} (pattern: {pattern})",
                    pattern=pattern,
                )

    # -- User Confirmation Query -------------------------------------------

    def needs_confirmation(
        self,
        agent_role: str,
        required_scopes: list[str] | None = None,
        tool_name: str | None = None,
        category: ActionCategory | None = None,
        risk: RiskLevel | None = None,
    ) -> bool:
        """Return ``True`` if action requires explicit user confirmation."""
        policy = self._resolve_policy(agent_role)
        if policy is None:
            return True  # no policy → be cautious

        # If scopes are given, check policy.require_user_confirmation
        if required_scopes:
            if bool(set(required_scopes) & policy.require_user_confirmation):
                return True

        # Check by category / risk level if tool name is known
        if tool_name and (category is None or risk is None):
            classification = self.get_tool_classification(tool_name, required_scopes)
            if classification:
                category, risk = classification

        # Policy-specific category or risk level confirmation
        if category and category in policy.confirm_categories:
            return True

        if risk and risk in policy.confirm_risk_levels:
            return True

        return False

    def get_policy(self, agent_role: str) -> Policy | None:
        """Return policy for *agent_role*, or ``None``."""
        return self._resolve_policy(agent_role)

    # -- Internal logging helper -------------------------------------------

    def _log_and_emit(
        self,
        agent_role: str,
        tool_name: str,
        arguments: dict[str, Any],
        decision: str,
        category: ActionCategory | None = None,
        risk: RiskLevel | None = None,
        error: str | None = None,
    ) -> None:
        """Record decision in audit log and emit event on EventBus."""
        cat_str = category.value if category else None
        risk_str = risk.value if risk else None

        if self._audit_log:
            self._audit_log.record_security_decision(
                agent_role=agent_role,
                tool_name=tool_name,
                arguments=arguments,
                decision=decision,
                action_category=cat_str,
                risk_level=risk_str,
                error=error,
            )

        if self._event_bus:
            # Non-blocking background publish
            event_type = f"security.{decision}" if decision != "allow" else "security.check"
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._event_bus.publish(
                            event_type,
                            {
                                "event_type": event_type,
                                "agent_role": agent_role,
                                "tool_name": tool_name,
                                "decision": decision,
                                "action_category": cat_str,
                                "risk_level": risk_str,
                                "error": error,
                            },
                        )
                    )
            except Exception:
                pass
