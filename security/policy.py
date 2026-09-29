"""Security policy definitions for NEXUS OS.

A Policy declares what an agent is and isn't allowed to do.  Policies
are loaded at startup and passed to the PermissionGate which enforces
them at tool-execution time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Policy:
    """Permission policy scoped to a single agent role.

    Attributes:
        agent_role: The agent role this policy applies to.
        allowed_scopes: Set of permission scope strings the agent may use
            (e.g. ``{"fs.read", "fs.write"}``).
        denied_paths: Filesystem paths the agent must never touch,
            regardless of scope.
        max_concurrent_tools: Concurrency cap for tool calls.
        require_user_confirmation: Scopes that need explicit user
            approval before execution (e.g. ``{"fs.delete"}``).
    """

    agent_role: str
    allowed_scopes: set[str] = field(default_factory=set)
    denied_paths: list[str] = field(default_factory=list)
    max_concurrent_tools: int = 5
    require_user_confirmation: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Default policies shipped with NEXUS OS
# ---------------------------------------------------------------------------

DEFAULT_POLICIES: dict[str, Policy] = {
    "supervisor": Policy(
        agent_role="supervisor",
        allowed_scopes=set(),  # supervisor delegates, never calls tools directly
    ),
    "file": Policy(
        agent_role="file",
        allowed_scopes={"fs.read", "fs.write", "fs.delete"},
        denied_paths=["/etc", "/boot", "/sys", "/proc", "/dev"],
        require_user_confirmation={"fs.delete"},
    ),
    "system": Policy(
        agent_role="system",
        allowed_scopes={"process.execute", "system.read"},
        require_user_confirmation={"process.execute"},
    ),
    "code": Policy(
        agent_role="code",
        allowed_scopes={"fs.read", "fs.write", "process.execute"},
        require_user_confirmation={"process.execute"},
    ),
    "web": Policy(
        agent_role="web",
        allowed_scopes={"network.http"},
    ),
    "app": Policy(
        agent_role="app",
        allowed_scopes={"app.list", "app.open", "app.close"},
        require_user_confirmation={"app.close"},
    ),
}
