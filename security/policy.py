"""Security policy definitions for NEXUS OS.

A Policy declares what an agent is and isn't allowed to do:
- Allowed scopes (e.g. fs.read, process.execute)
- Allowed tools (deny-by-default for unknown or unassigned tools)
- Maximum allowable risk level (blocking higher-risk actions)
- Restricted filesystem paths (denied paths)
- Confirmation requirements (by scope, category, or risk level)
- Shell execution privileges (privilege escalation defense)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from security.models import ActionCategory, RiskLevel


@dataclass
class Policy:
    """Permission policy scoped to a single agent role.

    Attributes:
        agent_role: The agent role this policy applies to.
        allowed_scopes: Set of permission scope strings the agent may use
            (e.g. ``{"fs.read", "fs.write"}``).
        allowed_tools: Set of specific tool names the agent is allowed to run.
            If ``None``, any registered tool within ``allowed_scopes`` is allowed.
        denied_paths: Filesystem paths the agent must never touch,
            regardless of scope.
        max_concurrent_tools: Concurrency cap for tool calls.
        require_user_confirmation: Scopes that need explicit user
            approval before execution (e.g. ``{"fs.delete"}``).
        confirm_categories: Action categories that need confirmation.
        confirm_risk_levels: Risk levels that need confirmation.
        max_risk_level: Highest risk level permitted for this agent.
        allow_shell: Whether the agent is permitted to execute host shell commands.
    """

    agent_role: str
    allowed_scopes: set[str] = field(default_factory=set)
    allowed_tools: set[str] | None = None
    denied_paths: list[str] = field(
        default_factory=lambda: ["/etc", "/boot", "/sys", "/proc", "/dev", "/root"]
    )
    max_concurrent_tools: int = 5
    require_user_confirmation: set[str] = field(default_factory=set)
    confirm_categories: set[ActionCategory] = field(default_factory=set)
    confirm_risk_levels: set[RiskLevel] = field(default_factory=set)
    max_risk_level: RiskLevel = RiskLevel.HIGH
    allow_shell: bool = False

    def is_scope_allowed(self, scope: str) -> bool:
        """Check if a specific permission scope is allowed."""
        return scope in self.allowed_scopes

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool name is permitted under this policy."""
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools

    def requires_confirmation_for(
        self,
        scope: str | None = None,
        category: ActionCategory | None = None,
        risk: RiskLevel | None = None,
    ) -> bool:
        """Evaluate if an action requires explicit user confirmation."""
        if scope and scope in self.require_user_confirmation:
            return True
        if category and category in self.confirm_categories:
            return True
        if risk and risk in self.confirm_risk_levels:
            return True
        return False


# ---------------------------------------------------------------------------
# Default policies shipped with NEXUS OS
# ---------------------------------------------------------------------------

_BASE_POLICIES: dict[str, Policy] = {
    "supervisor": Policy(
        agent_role="supervisor",
        allowed_scopes=set(),  # supervisor delegates, never calls tools directly
        allowed_tools=set(),
        max_risk_level=RiskLevel.LOW,
        allow_shell=False,
    ),
    "file": Policy(
        agent_role="file",
        allowed_scopes={"fs.read", "fs.write", "fs.delete"},
        allowed_tools={
            "file_read",
            "file_metadata",
            "file_search",
            "file_open_os",
            "file_mkdir",
            "file_move",
            "file_write",
            "file_delete",
        },
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev", "/root"],
        require_user_confirmation={"fs.delete"},
        confirm_categories={ActionCategory.DESTRUCTIVE},
        confirm_risk_levels={RiskLevel.HIGH},
        max_risk_level=RiskLevel.HIGH,
        allow_shell=False,
    ),
    "system": Policy(
        agent_role="system",
        allowed_scopes={"process.execute", "system.read"},
        allowed_tools={
            "system_info",
            "system_cpu",
            "system_memory",
            "system_disk",
            "system_os",
            "system_processes",
            "process_run",
        },
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev", "/root"],
        require_user_confirmation={"process.execute"},
        confirm_categories={ActionCategory.DESTRUCTIVE},
        confirm_risk_levels={RiskLevel.HIGH},
        max_risk_level=RiskLevel.HIGH,
        allow_shell=True,
    ),
    "code": Policy(
        agent_role="code",
        allowed_scopes={"fs.read", "fs.write", "process.execute"},
        allowed_tools=None,
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev", "/root"],
        require_user_confirmation={"process.execute"},
        confirm_categories={ActionCategory.DESTRUCTIVE},
        confirm_risk_levels={RiskLevel.HIGH},
        max_risk_level=RiskLevel.HIGH,
        allow_shell=True,
    ),
    "web": Policy(
        agent_role="web",
        allowed_scopes={"network.http"},
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev", "/root"],
        max_risk_level=RiskLevel.MEDIUM,
        allow_shell=False,
    ),
    "app": Policy(
        agent_role="app",
        allowed_scopes={"app.list", "app.open", "app.close"},
        allowed_tools={
            "app_list_installed",
            "app_list_running",
            "app_is_running",
            "app_open",
            "app_close",
        },
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev", "/root"],
        require_user_confirmation={"app.close"},
        confirm_categories={ActionCategory.SENSITIVE},
        max_risk_level=RiskLevel.MEDIUM,
        allow_shell=False,
    ),
    "vr_session": Policy(
        agent_role="vr_session",
        allowed_scopes={"window.interact", "ai.request"},
        allowed_tools={
            "window.created",
            "window.moved",
            "window.resized",
            "window.rotated",
            "window.focused",
            "window.grab_started",
            "window.grab_ended",
            "ai.request",
        },
        max_risk_level=RiskLevel.MEDIUM,
        allow_shell=False,
    ),
}

# Provide transparent alias mapping for canonical agent names like 'file_agent'
DEFAULT_POLICIES: dict[str, Policy] = dict(_BASE_POLICIES)
for role, policy in list(_BASE_POLICIES.items()):
    if not role.endswith("_agent"):
        alias_role = f"{role}_agent"
        if alias_role not in DEFAULT_POLICIES:
            alias_policy = Policy(
                agent_role=alias_role,
                allowed_scopes=set(policy.allowed_scopes),
                allowed_tools=set(policy.allowed_tools) if policy.allowed_tools is not None else None,
                denied_paths=list(policy.denied_paths),
                max_concurrent_tools=policy.max_concurrent_tools,
                require_user_confirmation=set(policy.require_user_confirmation),
                confirm_categories=set(policy.confirm_categories),
                confirm_risk_levels=set(policy.confirm_risk_levels),
                max_risk_level=policy.max_risk_level,
                allow_shell=policy.allow_shell,
            )
            DEFAULT_POLICIES[alias_role] = alias_policy
