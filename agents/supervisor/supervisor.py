"""Supervisor / Orchestrator agent for NEXUS OS.

The Supervisor is the **only** agent that the API layer talks to
directly.  It is responsible for:

1. Intent classification — understanding what the user wants
2. Agent routing         — choosing which specialized agent(s) to handle it
3. Plan construction     — building an ExecutionPlan for single or
                           multi-agent work
4. Execution             — running the plan via the PlanExecutor
5. Result aggregation    — combining results and updating context
6. Error recovery        — returning useful errors when agents fail

Routing is delegated to a pluggable :class:`RoutingStrategy` (keyword
matching by default, LLM-based when configured).
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.registry import AgentRegistry
from agents.supervisor.executor import PlanExecutor
from agents.supervisor.planner import ExecutionPlanner
from agents.supervisor.strategies import (
    AgentMeta,
    KeywordRoutingStrategy,
    LLMRoutingStrategy,
    RoutingStrategy,
)
from agents.supervisor.types import PipelineResult
from agents.supervisor.validator import ActionValidator
from agents.types import AgentContext, AgentResult, Capability
from context.manager import ContextManager

logger = logging.getLogger("nexus.supervisor")


class SupervisorAgent(BaseAgent):
    """Orchestrator that routes user requests to specialized agents.

    The Supervisor itself does **not** call tools directly.  It uses
    the LLM only for intent classification (when using
    ``LLMRoutingStrategy``) and response formatting for unmatched
    intents.

    Parameters:
        agent_registry:   Registry containing all available agents.
        context:          Shared context manager.
        routing_strategy: Pluggable intent classifier.  Defaults to
                          ``KeywordRoutingStrategy`` for backward
                          compatibility.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        context: ContextManager,
        routing_strategy: RoutingStrategy | None = None,
    ) -> None:
        super().__init__(
            name="supervisor",
            description=(
                "Orchestrates all other agents. Routes user intent to "
                "specialists and coordinates multi-agent workflows."
            ),
            capabilities=[
                Capability(
                    name="routing",
                    description="Classify intent and delegate to agents",
                ),
                Capability(
                    name="orchestration",
                    description="Coordinate multi-agent workflows",
                ),
            ],
        )
        self._registry = agent_registry
        self._context = context
        self._validator = ActionValidator(agent_registry)
        self._strategy: RoutingStrategy = (
            routing_strategy or KeywordRoutingStrategy()
        )
        self._planner = ExecutionPlanner()
        self._executor = PlanExecutor(agent_registry, context)

    # ── LLM & Routing strategy management ────────────────────────────────

    @property
    def validator(self) -> ActionValidator:
        """The action validator protecting capability boundaries and shell safety."""
        return self._validator

    def set_llm(self, provider: Any) -> None:
        """Inject LLM provider into the Supervisor and activate LLMRoutingStrategy."""
        super().set_llm(provider)
        # Activate LLMRoutingStrategy if currently using default keyword strategy
        if isinstance(self._strategy, KeywordRoutingStrategy):
            self._strategy = LLMRoutingStrategy(
                llm=provider,
                agent_registry=self._registry,
                validator=self._validator,
                fallback=self._strategy,
            )
            logger.info("Activated LLMRoutingStrategy with pre-execution validation")

    @property
    def routing_strategy(self) -> RoutingStrategy:
        """The currently active routing strategy."""
        return self._strategy

    def set_routing_strategy(self, strategy: RoutingStrategy) -> None:
        """Hot-swap the routing strategy at runtime.

        Useful for switching from keyword-based routing to LLM-based
        routing after the model backend becomes available.
        """
        self._strategy = strategy
        logger.info(
            "Routing strategy changed to %s",
            type(strategy).__name__,
        )

    # ── Main execution entry point ───────────────────────────────────────

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Route a user request to the appropriate agent(s).

        Architecture Flow:
            User → Supervisor → LLM → structured action → Agent → Tool → Linux

        1. Record user message in conversation context
        2. Query LLM routing strategy with intent and conversation context
        3. Validate structured actions against capability schemas and shell safety
        4. Build an execution plan (single, sequential, or parallel)
        5. Execute the plan through the PlanExecutor
        6. Record the assistant response in context
        7. Return aggregated result
        """
        # 1. Record user message
        self._context.add_message(ctx.session_id, "user", ctx.intent)

        # 2. Classify intent with conversation history support
        history = self._context.get_history(ctx.session_id)
        agent_metas = self._build_agent_metas()
        classification = await self._strategy.classify(
            ctx.intent,
            agent_metas,
            conversation_history=history,
        )

        logger.info(
            "Intent classified: primary=%s  confidence=%.2f  multi=%s  actions=%d",
            classification.primary_agent,
            classification.confidence,
            classification.requires_multi_agent,
            len(classification.actions),
        )

        # 3. Route & Execute
        if classification.metadata.get("validation_error"):
            # Action was rejected by ActionValidator (security or schema failure)
            result = AgentResult(
                success=False,
                error=classification.metadata["validation_error"],
                output=classification.direct_response or "",
                data={"agent_used": "supervisor", "validation_failed": True},
            )
        elif classification.direct_response and not classification.actions and not classification.primary_agent:
            # LLM answered conversationally without requiring tool invocation
            result = AgentResult(
                success=True,
                output=classification.direct_response,
                data={"agent_used": "supervisor"},
            )
        elif not classification.actions and classification.primary_agent is None:
            # No agent matched and no LLM direct response → fallback to general response
            result = await self._handle_general(ctx)
            result.data["agent_used"] = "supervisor"
        else:
            # 4. Build execution plan from actions or classification
            plan = self._planner.build_plan(
                classification, ctx.session_id,
            )

            # 5. Execute plan through PlanExecutor
            pipeline_result = await self._executor.execute(
                plan, ctx.session_id,
            )

            # 6. Convert PipelineResult → AgentResult
            result = self._aggregate_result(pipeline_result, plan)

        # 7. Record assistant response in context
        if result.output:
            self._context.add_message(
                ctx.session_id, "assistant", result.output,
            )

        return result

    # ── Result aggregation ───────────────────────────────────────────────

    def _aggregate_result(
        self,
        pipeline: PipelineResult,
        plan: Any,
    ) -> AgentResult:
        """Convert a :class:`PipelineResult` into the standard
        :class:`AgentResult` that the API layer expects.
        """
        # For single-agent plans, report that specific agent.
        # For multi-agent plans, report "supervisor" as the coordinator.
        agent_used = (
            pipeline.agents_used[0]
            if len(pipeline.agents_used) == 1
            else "supervisor"
        )

        tool_calls = []
        for step in pipeline.steps:
            if step.result and getattr(step.result, "tool_calls_made", None):
                tool_calls.extend(step.result.tool_calls_made)

        return AgentResult(
            success=pipeline.success,
            output=pipeline.final_output,
            error="; ".join(pipeline.errors) if pipeline.errors else None,
            tool_calls_made=tool_calls,
            data={
                "agent_used": agent_used,
                "agents_used": pipeline.agents_used,
                "plan_id": pipeline.plan_id,
                "execution_mode": plan.mode.value,
                "step_count": len(pipeline.steps),
            },
            duration_ms=pipeline.total_duration_ms,
        )

    # ── Fallback handler ─────────────────────────────────────────────────

    async def _handle_general(self, ctx: AgentContext) -> AgentResult:
        """Handle requests that don't match any specialized agent.

        Uses the LLM to generate a helpful response listing available
        capabilities.
        """
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are NEXUS OS, an AI-first operating environment. "
                    "The user's request did not match a specialized agent. "
                    "Answer helpfully and suggest what you can do.\n\n"
                    "Available agents: "
                    + ", ".join(
                        f"{a.name} ({a.description})"
                        for a in self._registry
                    )
                ),
            },
            {"role": "user", "content": ctx.intent},
        ]

        try:
            response = await self.think(messages, tools=[])
            return AgentResult(output=response.content)
        except Exception as exc:
            logger.exception("General handling failed")
            return AgentResult(success=False, error=str(exc))

    # ── Agent metadata helpers ───────────────────────────────────────────

    def _build_agent_metas(self) -> list[AgentMeta]:
        """Build lightweight agent descriptors for the routing strategy."""
        return [
            AgentMeta(
                name=agent.name,
                description=agent.description,
                capabilities=[c.name for c in agent.capabilities],
            )
            for agent in self._registry
        ]

    # ── Lifecycle ────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Called by the API lifespan on application startup.

        Starts all registered agents and then the supervisor itself.
        """
        self._registry.start_all()
        self.on_start()

    def shutdown(self) -> None:
        """Called by the API lifespan on application shutdown.

        Stops all registered agents and then the supervisor itself.
        """
        self._registry.stop_all()
        self.on_stop()

    # ── Introspection helpers for API ────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """Return metadata for all registered agents."""
        return self._registry.describe_all()
