"""Execution planner for the NEXUS Supervisor.

Transforms an :class:`IntentClassification` into a concrete
:class:`ExecutionPlan` that the :class:`PlanExecutor` can run.

Planning rules
──────────────
* **No agent matched** → empty plan (triggers the Supervisor's fallback).
* **Single agent** → ``SINGLE`` mode with one step.
* **Multi-agent, all independent** → ``PARALLEL`` mode.
* **Multi-agent, with dependencies** → ``SEQUENTIAL`` mode.
"""

from __future__ import annotations

import logging

from agents.supervisor.types import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    IntentClassification,
)

logger = logging.getLogger("nexus.supervisor.planner")


class ExecutionPlanner:
    """Builds :class:`ExecutionPlan` instances from classified intents."""

    def build_plan(
        self,
        classification: IntentClassification,
        session_id: str,
    ) -> ExecutionPlan:
        """Convert a classification into a runnable plan.

        Parameters:
            classification: The output of a routing strategy.
            session_id:     Active session (used for logging/tracing).

        Returns:
            An ``ExecutionPlan`` ready for the executor.
        """
        # 1. If structured LLM actions are present, build plan from them
        if classification.actions:
            return self._build_plan_from_actions(classification)

        # 2. Multi-agent sub-intents
        if (
            classification.requires_multi_agent
            and classification.sub_intents
        ):
            return self._build_multi_plan(classification)

        # 3. Single-agent fallback
        return self._build_single_plan(classification)

    # ── LLM structured actions plan ──────────────────────────────────────

    def _build_plan_from_actions(
        self,
        classification: IntentClassification,
    ) -> ExecutionPlan:
        """Build execution plan directly from validated structured actions."""
        steps: list[ExecutionStep] = []
        has_dependencies = False

        for idx, act in enumerate(classification.actions):
            step_id = act.step_id if act.step_id is not None else idx
            deps = list(act.depends_on or [])
            if deps:
                has_dependencies = True

            step = ExecutionStep(
                step_id=step_id,
                agent_name=act.agent_name,
                intent=act.thought or f"Execute {act.tool_name}",
                parameters={
                    "tool_name": act.tool_name,
                    "arguments": act.arguments,
                },
                depends_on=deps,
                action=act,
            )
            steps.append(step)

        if len(steps) == 1:
            mode = ExecutionMode.SINGLE
        elif has_dependencies:
            mode = ExecutionMode.SEQUENTIAL
        else:
            mode = ExecutionMode.PARALLEL

        return ExecutionPlan(
            mode=mode,
            steps=steps,
            original_intent=classification.raw_intent,
            classification=classification,
            metadata={"source": "llm_actions"},
        )

    # ── Single-agent plan ────────────────────────────────────────────────

    def _build_single_plan(
        self,
        classification: IntentClassification,
    ) -> ExecutionPlan:
        """One agent, one step — or zero steps if nothing matched."""
        if classification.primary_agent is None:
            # No agent matched → plan with zero steps (triggers fallback)
            return ExecutionPlan(
                mode=ExecutionMode.SINGLE,
                original_intent=classification.raw_intent,
                classification=classification,
            )

        step = ExecutionStep(
            step_id=0,
            agent_name=classification.primary_agent,
            intent=classification.raw_intent,
        )

        logger.debug(
            "Single-agent plan: %.60s → %s",
            classification.raw_intent,
            classification.primary_agent,
        )

        return ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            steps=[step],
            original_intent=classification.raw_intent,
            classification=classification,
        )

    # ── Multi-agent plan ─────────────────────────────────────────────────

    def _build_multi_plan(
        self,
        classification: IntentClassification,
    ) -> ExecutionPlan:
        """Multiple agents — sequential or parallel based on deps."""
        steps: list[ExecutionStep] = []
        for idx, sub in enumerate(classification.sub_intents):
            steps.append(
                ExecutionStep(
                    step_id=idx,
                    agent_name=sub.target_agent,
                    intent=sub.description,
                    parameters=sub.parameters,
                    depends_on=sub.depends_on,
                )
            )

        # Determine execution mode from the dependency graph
        has_deps = any(s.depends_on for s in steps)
        mode = ExecutionMode.SEQUENTIAL if has_deps else ExecutionMode.PARALLEL

        agents_involved = [s.agent_name for s in steps]
        joiner = " → " if has_deps else " + "
        logger.info(
            "Multi-agent %s plan: %s (%d steps)",
            mode.value,
            joiner.join(agents_involved),
            len(steps),
        )

        return ExecutionPlan(
            mode=mode,
            steps=steps,
            original_intent=classification.raw_intent,
            classification=classification,
        )
