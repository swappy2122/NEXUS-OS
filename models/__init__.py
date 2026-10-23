"""NEXUS OS AI Models Subsystem (Local LLMs, Vision, Embeddings)."""

from models.base_backend import BaseModelBackend
from models.dev_backend import DevModelBackend
from models.router import ModelRouter
from models.routing_strategy import (
    DefaultPassthroughStrategy,
    ModelRoutingStrategy,
    RuleBasedStrategy,
)
from models.routing_types import (
    ComplexityTier,
    ModelTierConfig,
    RoutingDecision,
    TaskCategory,
)

__all__ = [
    # Core
    "ModelRouter",
    "BaseModelBackend",
    "DevModelBackend",
    # Strategy
    "ModelRoutingStrategy",
    "RuleBasedStrategy",
    "DefaultPassthroughStrategy",
    # Types
    "TaskCategory",
    "ComplexityTier",
    "RoutingDecision",
    "ModelTierConfig",
]
