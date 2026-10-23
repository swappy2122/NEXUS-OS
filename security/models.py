"""Security models, categories, and risk levels for NEXUS OS.

Defines the core taxonomy for the NEXUS Security and Permission Layer:
- ActionCategory: read-only, normal, sensitive, destructive
- RiskLevel: low, medium, high, critical
- SecurityDecision: allow, deny, require_confirmation
- ConfirmationStatus: pending, approved, rejected, expired
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ActionCategory(str, Enum):
    """Classification of tool action types according to impact.

    Categories:
    - READ_ONLY: Pure inspection of system state or file reading (no state modification).
    - NORMAL: Everyday user actions (e.g. launching an app, creating a folder).
    - SENSITIVE: State alterations that modify data or disrupt workflows (e.g. moving/overwriting files, closing apps).
    - DESTRUCTIVE: Irreversible or high-impact operations (e.g. file deletion, arbitrary process/shell execution).
    """

    READ_ONLY = "read_only"
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class RiskLevel(str, Enum):
    """Risk severity levels associated with actions or tools.

    Supports ordering comparisons (e.g. RiskLevel.HIGH > RiskLevel.LOW).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def severity_rank(self) -> int:
        """Numeric rank for severity comparison."""
        ranks = {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }
        return ranks.get(self.value, 1)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity_rank < other.severity_rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity_rank <= other.severity_rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity_rank > other.severity_rank

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self.severity_rank >= other.severity_rank


class SecurityDecision(str, Enum):
    """The outcome of a security policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


class ConfirmationStatus(str, Enum):
    """Status of an action pending user confirmation."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Default Tool Security Classification Taxonomy
# ---------------------------------------------------------------------------

DEFAULT_TOOL_CLASSIFICATIONS: dict[str, tuple[ActionCategory, RiskLevel]] = {
    # ── Read-Only Actions (Low Risk) ────────────────────────────────────────
    "file_read": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "file_metadata": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "file_search": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_info": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_cpu": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_memory": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_disk": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_os": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "system_processes": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "app_list_installed": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "app_list_running": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "app_is_running": (ActionCategory.READ_ONLY, RiskLevel.LOW),

    # ── Normal User Actions (Low Risk) ──────────────────────────────────────
    "app_open": (ActionCategory.NORMAL, RiskLevel.LOW),
    "file_open_os": (ActionCategory.NORMAL, RiskLevel.LOW),
    "file_mkdir": (ActionCategory.NORMAL, RiskLevel.LOW),

    # ── Sensitive Actions (Medium Risk) ─────────────────────────────────────
    "file_move": (ActionCategory.SENSITIVE, RiskLevel.MEDIUM),
    "file_write": (ActionCategory.SENSITIVE, RiskLevel.MEDIUM),
    "app_close": (ActionCategory.SENSITIVE, RiskLevel.MEDIUM),

    # ── Destructive Actions (High Risk) ─────────────────────────────────────
    "file_delete": (ActionCategory.DESTRUCTIVE, RiskLevel.HIGH),
    "process_run": (ActionCategory.DESTRUCTIVE, RiskLevel.HIGH),
}


# Default scope to risk/category mapping fallback (when tool name is unlisted)
DEFAULT_SCOPE_CLASSIFICATIONS: dict[str, tuple[ActionCategory, RiskLevel]] = {
    "system.read": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "app.list": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "fs.read": (ActionCategory.READ_ONLY, RiskLevel.LOW),
    "app.open": (ActionCategory.NORMAL, RiskLevel.LOW),
    "app.close": (ActionCategory.SENSITIVE, RiskLevel.MEDIUM),
    "fs.write": (ActionCategory.SENSITIVE, RiskLevel.MEDIUM),
    "network.http": (ActionCategory.NORMAL, RiskLevel.LOW),
    "fs.delete": (ActionCategory.DESTRUCTIVE, RiskLevel.HIGH),
    "process.execute": (ActionCategory.DESTRUCTIVE, RiskLevel.HIGH),
}


def classify_tool(
    tool_name: str,
    required_scopes: list[str] | None = None,
) -> tuple[ActionCategory, RiskLevel] | None:
    """Classify a tool into its ActionCategory and RiskLevel.

    Returns ``None`` if the tool is completely unknown and cannot be
    inferred from recognized scopes (enabling deny-by-default).
    """
    if tool_name in DEFAULT_TOOL_CLASSIFICATIONS:
        return DEFAULT_TOOL_CLASSIFICATIONS[tool_name]

    if required_scopes:
        # Highest risk scope determines classification
        highest: tuple[ActionCategory, RiskLevel] | None = None
        for scope in required_scopes:
            if scope in DEFAULT_SCOPE_CLASSIFICATIONS:
                cand = DEFAULT_SCOPE_CLASSIFICATIONS[scope]
                if highest is None or cand[1] > highest[1]:
                    highest = cand
        if highest is not None:
            return highest

    return None


@dataclass
class SecurityCheckResult:
    """Detailed result of a security gate evaluation."""

    decision: SecurityDecision
    reason: str
    agent_role: str
    tool_name: str
    action_category: ActionCategory
    risk_level: RiskLevel
    confirmation_required: bool = False
    confirmation_request_id: str | None = None
    sanitized_arguments: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_allowed(self) -> bool:
        """Whether execution is authorized to proceed immediately."""
        return self.decision == SecurityDecision.ALLOW
