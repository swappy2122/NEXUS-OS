"""NEXUS OS Supervisor / Orchestrator package.

Re-exports the main ``SupervisorAgent`` class so that existing imports
like ``from agents.supervisor import SupervisorAgent`` continue to work
without modification.

Submodules
──────────
* ``types``      — IntentClassification, ExecutionPlan, ExecutionStep, etc.
* ``strategies`` — Pluggable RoutingStrategy implementations
* ``planner``    — Builds ExecutionPlans from classified intents
* ``executor``   — Runs plans (single / sequential / parallel)
* ``supervisor`` — The SupervisorAgent itself
"""

from agents.supervisor.supervisor import SupervisorAgent
from agents.supervisor.strategies import (
    AgentMeta,
    CapabilityRoutingStrategy,
    KeywordRoutingStrategy,
    LLMRoutingStrategy,
    RoutingStrategy,
)
from agents.supervisor.types import (
    ActionValidationResult,
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    IntentClassification,
    LLMPlanOutput,
    PipelineResult,
    StepStatus,
    StructuredAction,
    SubIntent,
)
from agents.supervisor.validator import ActionValidator

__all__ = [
    # Core
    "SupervisorAgent",
    "ActionValidator",
    # Strategies
    "RoutingStrategy",
    "KeywordRoutingStrategy",
    "CapabilityRoutingStrategy",
    "LLMRoutingStrategy",
    "AgentMeta",
    # Types
    "IntentClassification",
    "SubIntent",
    "StructuredAction",
    "ActionValidationResult",
    "LLMPlanOutput",
    "ExecutionMode",
    "ExecutionStep",
    "ExecutionPlan",
    "PipelineResult",
    "StepStatus",
]
