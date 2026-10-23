"""NEXUS OS Security Subsystem.

Provides comprehensive permission gating, risk classification, privilege
escalation prevention, user confirmation handling, and audit logging.
"""

from security.audit import AuditEntry, AuditLog
from security.confirmation import (
    AutoApproveConfirmation,
    AutoRejectConfirmation,
    CallbackConfirmation,
    ConfirmationProvider,
    ConfirmationRequest,
    InteractiveCLIConfirmation,
    TokenStoreConfirmation,
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
    ConfirmationStatus,
    RiskLevel,
    SecurityCheckResult,
    SecurityDecision,
    classify_tool,
)
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES, Policy

__all__ = [
    # Models & Enums
    "ActionCategory",
    "RiskLevel",
    "SecurityDecision",
    "ConfirmationStatus",
    "SecurityCheckResult",
    "classify_tool",
    # Policies & Gate
    "Policy",
    "DEFAULT_POLICIES",
    "PermissionGate",
    # Exceptions
    "SecurityError",
    "PermissionDenied",
    "UnknownToolError",
    "PrivilegeEscalationError",
    "RestrictedPathError",
    "DangerousCommandError",
    "ConfirmationRequiredError",
    "ConfirmationRejectedError",
    # Confirmation
    "ConfirmationRequest",
    "ConfirmationProvider",
    "AutoApproveConfirmation",
    "AutoRejectConfirmation",
    "CallbackConfirmation",
    "TokenStoreConfirmation",
    "InteractiveCLIConfirmation",
    # Audit
    "AuditLog",
    "AuditEntry",
]
