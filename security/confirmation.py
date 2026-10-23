"""User confirmation mechanisms for sensitive and destructive actions in NEXUS OS.

Provides pluggable confirmation providers:
- AutoApproveConfirmation: automatically approves (for test suites / headless execution)
- AutoRejectConfirmation: automatically rejects (safe default when no user interface is attached)
- CallbackConfirmation: delegates to custom sync/async functions (UI dialogs, webhooks)
- InteractiveCLIConfirmation: terminal prompt with timeout
- TokenStoreConfirmation: holds pending requests for external resolution via API/CLI
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from security.models import ActionCategory, ConfirmationStatus, RiskLevel

logger = logging.getLogger("NEXUS_OS.security.confirmation")


@dataclass
class ConfirmationRequest:
    """Represents a request for explicit user confirmation before executing an action."""

    agent_role: str
    tool_name: str
    arguments: dict[str, Any]
    action_category: ActionCategory
    risk_level: RiskLevel
    reason: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    def approve(self, approver: str = "user") -> None:
        """Mark this confirmation request as approved."""
        self.status = ConfirmationStatus.APPROVED
        self.resolved_at = datetime.now(timezone.utc)
        self.resolved_by = approver

    def reject(self, rejector: str = "user") -> None:
        """Mark this confirmation request as rejected."""
        self.status = ConfirmationStatus.REJECTED
        self.resolved_at = datetime.now(timezone.utc)
        self.resolved_by = rejector

    def to_dict(self) -> dict[str, Any]:
        """Convert confirmation request to a dictionary for API / UI."""
        return {
            "request_id": self.request_id,
            "agent_role": self.agent_role,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "action_category": self.action_category.value,
            "risk_level": self.risk_level.value,
            "reason": self.reason,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
        }


@runtime_checkable
class ConfirmationProvider(Protocol):
    """Protocol for handling user confirmation requests."""

    async def request_confirmation(self, request: ConfirmationRequest) -> bool:
        """Prompt user or evaluation hook for confirmation.

        Returns ``True`` if authorized, ``False`` if rejected.
        """
        ...


class AutoApproveConfirmation:
    """Confirmation provider that approves all requests (for testing or automated pipelines)."""

    async def request_confirmation(self, request: ConfirmationRequest) -> bool:
        logger.info(
            "Auto-approving confirmation for agent=%s tool=%s (risk=%s)",
            request.agent_role,
            request.tool_name,
            request.risk_level.value,
        )
        request.approve(approver="auto_approve")
        return True


class AutoRejectConfirmation:
    """Confirmation provider that rejects all requests (safe deny default when unattended)."""

    async def request_confirmation(self, request: ConfirmationRequest) -> bool:
        logger.warning(
            "Auto-rejecting confirmation for agent=%s tool=%s (risk=%s)",
            request.agent_role,
            request.tool_name,
            request.risk_level.value,
        )
        request.reject(rejector="auto_reject")
        return False


class CallbackConfirmation:
    """Delegates confirmation requests to an injected callback (sync or async)."""

    def __init__(
        self,
        callback: Callable[[ConfirmationRequest], bool | Awaitable[bool]],
    ) -> None:
        self._callback = callback

    async def request_confirmation(self, request: ConfirmationRequest) -> bool:
        try:
            res = self._callback(request)
            if inspect.isawaitable(res):
                approved = await res
            else:
                approved = bool(res)

            if approved:
                request.approve(approver="callback")
            else:
                request.reject(rejector="callback")
            return approved
        except Exception as exc:
            logger.exception("Error during confirmation callback evaluation: %s", exc)
            request.reject(rejector=f"error:{exc}")
            return False


class TokenStoreConfirmation:
    """Stores confirmation requests in memory for asynchronous approval/rejection (e.g. via REST/WebSocket)."""

    def __init__(self) -> None:
        self._pending: dict[str, ConfirmationRequest] = {}
        self._history: list[ConfirmationRequest] = []
        self._events: dict[str, asyncio.Event] = {}

    def get_pending(self) -> list[ConfirmationRequest]:
        """List all currently pending confirmation requests."""
        return list(self._pending.values())

    def get_request(self, request_id: str) -> ConfirmationRequest | None:
        """Lookup a request by ID."""
        return self._pending.get(request_id)

    def approve(self, request_id: str, approver: str = "user") -> bool:
        """Approve a pending request."""
        req = self._pending.get(request_id)
        if req and req.status == ConfirmationStatus.PENDING:
            req.approve(approver)
            if request_id in self._events:
                self._events[request_id].set()
            return True
        return False

    def reject(self, request_id: str, rejector: str = "user") -> bool:
        """Reject a pending request."""
        req = self._pending.get(request_id)
        if req and req.status == ConfirmationStatus.PENDING:
            req.reject(rejector)
            if request_id in self._events:
                self._events[request_id].set()
            return True
        return False

    async def request_confirmation(
        self,
        request: ConfirmationRequest,
        timeout: float = 60.0,
    ) -> bool:
        """Store request and await external approval or timeout."""
        self._pending[request.request_id] = request
        self._history.append(request)
        event = asyncio.Event()
        self._events[request.request_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return request.status == ConfirmationStatus.APPROVED
        except asyncio.TimeoutError:
            request.status = ConfirmationStatus.EXPIRED
            request.reject(rejector="timeout")
            logger.warning("Confirmation request %s timed out after %.1fs", request.request_id, timeout)
            return False
        finally:
            self._pending.pop(request.request_id, None)
            self._events.pop(request.request_id, None)


class InteractiveCLIConfirmation:
    """Prompts the user directly via standard I/O in terminal environments."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def request_confirmation(self, request: ConfirmationRequest) -> bool:
        loop = asyncio.get_running_loop()
        prompt_text = (
            f"\n⚠️  [NEXUS SECURITY CONFIRMATION]\n"
            f"Agent:    {request.agent_role}\n"
            f"Tool:     {request.tool_name}\n"
            f"Category: {request.action_category.value.upper()}\n"
            f"Risk:     {request.risk_level.value.upper()}\n"
            f"Args:     {request.arguments}\n"
            f"Allow execution? [y/N]: "
        )

        def _ask() -> bool:
            try:
                ans = input(prompt_text).strip().lower()
                return ans in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                return False

        try:
            approved = await asyncio.wait_for(
                loop.run_in_executor(None, _ask),
                timeout=self.timeout,
            )
            if approved:
                request.approve(approver="interactive_cli")
            else:
                request.reject(rejector="interactive_cli")
            return approved
        except asyncio.TimeoutError:
            print("\n[NEXUS SECURITY] Confirmation timed out. Request denied.")
            request.reject(rejector="cli_timeout")
            return False
