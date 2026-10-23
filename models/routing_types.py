"""Routing types for the NEXUS OS Model Router.

Defines the data contracts used by :class:`~models.routing_strategy.ModelRoutingStrategy`
and consumed by :class:`~models.router.ModelRouter`:

* **TaskCategory**      — what kind of work the request represents
* **ComplexityTier**    — how much model power is needed
* **RoutingDecision**   — the strategy's verdict for a single request
* **ModelTierConfig**   — maps complexity tiers to registered backend names
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Task Categories
# ---------------------------------------------------------------------------

class TaskCategory(str, Enum):
    """Classifies the *kind* of work a request represents.

    Used by routing strategies to decide how much model power is needed
    and whether an LLM call is required at all.
    """

    SIMPLE_OS_COMMAND = "simple_os_command"
    """Deterministic shell, file, or app operations (ls, open, mkdir …)."""

    GENERAL_REASONING = "general_reasoning"
    """Conversation, planning, general Q&A."""

    CODING = "coding"
    """Code generation, refactoring, debugging, or explanation."""

    VISION = "vision"
    """Image understanding, spatial reasoning, screenshot analysis."""

    SPEECH = "speech"
    """Voice input/output processing (future)."""

    UNKNOWN = "unknown"
    """Fallback when the strategy cannot determine the category."""


# ---------------------------------------------------------------------------
# Complexity Tiers
# ---------------------------------------------------------------------------

class ComplexityTier(str, Enum):
    """How much model power a request demands.

    Each tier maps to a registered backend via :class:`ModelTierConfig`.
    The special ``BYPASS`` tier skips the LLM entirely.
    """

    BYPASS = "bypass"
    """No LLM call needed — the response is deterministic."""

    LIGHT = "light"
    """Small / fast model sufficient (simple summarisation, short answers)."""

    STANDARD = "standard"
    """Default model — good balance of quality vs. cost."""

    HEAVY = "heavy"
    """Most capable model (complex reasoning, long code generation)."""


# ---------------------------------------------------------------------------
# Routing Decision
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """The verdict produced by a :class:`ModelRoutingStrategy`.

    The :class:`~models.router.ModelRouter` inspects this to decide
    which backend to call — or whether to skip the call entirely.

    Attributes:
        category:        What kind of task this is.
        tier:            How much model power is required.
        backend_override: If set, forces a specific backend name,
                          bypassing the tier → backend mapping.
        reason:          Human-readable explanation of the decision.
        bypass_response: Pre-built response for ``BYPASS`` tier.
                         The router returns this directly without
                         calling any backend.
        metadata:        Optional extra data for logging / telemetry.
    """

    category: TaskCategory = TaskCategory.UNKNOWN
    tier: ComplexityTier = ComplexityTier.STANDARD
    backend_override: str | None = None
    reason: str = ""
    bypass_response: Any | None = None  # ModelResponse when tier == BYPASS
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier → Backend Configuration
# ---------------------------------------------------------------------------

@dataclass
class ModelTierConfig:
    """Maps each :class:`ComplexityTier` to a registered backend name.

    Loaded from ``nexus.toml`` or constructed programmatically.
    Backend names must match those passed to
    :meth:`~models.router.ModelRouter.register_backend`.

    Example TOML::

        [routing.tiers]
        bypass   = "dev_backend"
        light    = "ollama"
        standard = "ollama"
        heavy    = "ollama"
    """

    bypass: str = "dev_backend"
    light: str = "default"
    standard: str = "default"
    heavy: str = "default"

    def get_backend_for_tier(self, tier: ComplexityTier) -> str:
        """Return the backend name mapped to *tier*."""
        return {
            ComplexityTier.BYPASS: self.bypass,
            ComplexityTier.LIGHT: self.light,
            ComplexityTier.STANDARD: self.standard,
            ComplexityTier.HEAVY: self.heavy,
        }[tier]

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ModelTierConfig:
        """Build from a flat dict (e.g. parsed TOML section)."""
        return cls(
            bypass=data.get("bypass", "dev_backend"),
            light=data.get("light", "default"),
            standard=data.get("standard", "default"),
            heavy=data.get("heavy", "default"),
        )
