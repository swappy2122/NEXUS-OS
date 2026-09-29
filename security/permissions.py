"""Permission gate for NEXUS OS.

The PermissionGate sits between agents and the tool layer.  Every
tool execution must pass through ``check()`` before the tool's
``execute()`` method is called.
"""

from __future__ import annotations

import logging
from typing import Any

from security.policy import Policy

logger = logging.getLogger("NEXUS_OS.security")


class PermissionDenied(Exception):
    """Raised when an agent attempts an action it is not authorised for."""

    def __init__(self, agent_role: str, detail: str) -> None:
        self.agent_role = agent_role
        self.detail = detail
        super().__init__(f"[{agent_role}] {detail}")


class PermissionGate:
    """Enforces per-agent permission policies.

    Parameters:
        policies: Mapping of ``agent_role`` → :class:`Policy`.
    """

    def __init__(self, policies: dict[str, Policy]) -> None:
        self._policies = policies

    # -- public API --------------------------------------------------------

    def check(
        self,
        agent_role: str,
        required_scopes: list[str],
        target_path: str | None = None,
    ) -> bool:
        """Return ``True`` if *agent_role* holds all *required_scopes*.

        Optionally checks *target_path* against the policy's denied-path
        list.

        Raises:
            PermissionDenied: When the check fails (provides a
                human-readable reason).
        """
        policy = self._policies.get(agent_role)
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
            for denied in policy.denied_paths:
                if target_path == denied or target_path.startswith(denied + "/"):
                    raise PermissionDenied(
                        agent_role,
                        f"Access to path '{target_path}' is denied by policy",
                    )

        return True

    def needs_confirmation(
        self,
        agent_role: str,
        required_scopes: list[str],
    ) -> bool:
        """Return ``True`` if any of *required_scopes* needs user confirmation."""
        policy = self._policies.get(agent_role)
        if policy is None:
            return True  # no policy → be cautious
        return bool(set(required_scopes) & policy.require_user_confirmation)

    def get_policy(self, agent_role: str) -> Policy | None:
        """Return the policy for *agent_role*, or ``None``."""
        return self._policies.get(agent_role)
