"""Plan executor for the NEXUS Supervisor.

Runs :class:`ExecutionPlan` instances by dispatching each step to its
target agent via the :class:`AgentRegistry`.

Execution modes
───────────────
* **SINGLE**     — one step dispatched to one agent.
* **SEQUENTIAL** — steps executed in order; a step is skipped if any of
  its dependencies failed.
* **PARALLEL**   — independent steps executed concurrently via
  ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agents.registry import AgentRegistry
from agents.supervisor.types import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    PipelineResult,
    StepStatus,
)
from agents.types import AgentContext, AgentResult
from context.manager import ContextManager

logger = logging.getLogger("nexus.supervisor.executor")


class PlanExecutor:
    """Executes an :class:`ExecutionPlan` against live agents.

    Parameters:
        registry: The agent registry containing all available agents.
        context:  Shared context manager for snapshot building.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        context: ContextManager,
    ) -> None:
        self._registry = registry
        self._context = context

    # ── Public entry point ───────────────────────────────────────────────

    async def execute(
        self,
        plan: ExecutionPlan,
        session_id: str,
    ) -> PipelineResult:
        """Run all steps in *plan* according to its execution mode.

        Returns a :class:`PipelineResult` with per-step outcomes,
        combined output, and timing.
        """
        start = time.monotonic()

        if plan.mode == ExecutionMode.SINGLE:
            result = await self._execute_single(plan, session_id)
        elif plan.mode == ExecutionMode.SEQUENTIAL:
            result = await self._execute_sequential(plan, session_id)
        elif plan.mode == ExecutionMode.PARALLEL:
            result = await self._execute_parallel(plan, session_id)
        else:
            result = PipelineResult(
                plan_id=plan.plan_id,
                success=False,
                errors=[f"Unknown execution mode: {plan.mode}"],
            )

        result.total_duration_ms = (time.monotonic() - start) * 1000
        result.plan_id = plan.plan_id
        return result

    # ── Single dispatch ──────────────────────────────────────────────────

    async def _execute_single(
        self,
        plan: ExecutionPlan,
        session_id: str,
    ) -> PipelineResult:
        """Run a plan with exactly one step."""
        if not plan.steps:
            return PipelineResult(
                success=False,
                errors=["Empty plan — no steps to execute"],
            )

        step = plan.steps[0]
        agent_result = await self._run_step(step, session_id)

        return PipelineResult(
            success=agent_result.success,
            steps=[step],
            final_output=agent_result.output,
            errors=[agent_result.error] if agent_result.error else [],
            agents_used=[step.agent_name],
        )

    # ── Sequential pipeline ─────────────────────────────────────────────

    async def _execute_sequential(
        self,
        plan: ExecutionPlan,
        session_id: str,
    ) -> PipelineResult:
        """Run steps in order, respecting dependency constraints.

        A step is **skipped** if any of its ``depends_on`` steps did
        not complete successfully.  Prior step outputs are forwarded
        in the context metadata so downstream agents can use them.
        """
        completed_results: dict[int, AgentResult] = {}
        errors: list[str] = []
        all_success = True

        for step in plan.steps:
            # Check that dependencies are satisfied
            unmet = [
                dep for dep in step.depends_on
                if dep not in completed_results
                or not completed_results[dep].success
            ]
            if unmet:
                step.status = StepStatus.SKIPPED
                errors.append(
                    f"Step {step.step_id} ({step.agent_name}) skipped: "
                    f"unmet dependencies {unmet}"
                )
                continue

            # Gather outputs from prior steps as context
            prior_outputs = {
                sid: r.output
                for sid, r in completed_results.items()
            }

            agent_result = await self._run_step(
                step,
                session_id,
                prior_results=prior_outputs,
            )
            completed_results[step.step_id] = agent_result

            if not agent_result.success:
                all_success = False
                if agent_result.error:
                    errors.append(
                        f"Step {step.step_id} ({step.agent_name}): "
                        f"{agent_result.error}"
                    )

        # Final output is the last completed step's output
        last_output = ""
        agents_used: list[str] = []
        for step in plan.steps:
            if step.result and step.status == StepStatus.COMPLETED:
                last_output = step.result.output
                agents_used.append(step.agent_name)

        return PipelineResult(
            success=all_success,
            steps=list(plan.steps),
            final_output=last_output,
            errors=errors,
            agents_used=agents_used,
        )

    # ── Parallel fan-out ─────────────────────────────────────────────────

    async def _execute_parallel(
        self,
        plan: ExecutionPlan,
        session_id: str,
    ) -> PipelineResult:
        """Run all steps concurrently and merge the results.

        Step outputs are joined with double newlines in the order they
        were defined in the plan (not completion order).
        """
        tasks = [
            self._run_step(step, session_id)
            for step in plan.steps
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors: list[str] = []
        outputs: list[str] = []
        agents_used: list[str] = []
        all_success = True

        for step, result in zip(plan.steps, results):
            if isinstance(result, Exception):
                step.status = StepStatus.FAILED
                step.result = AgentResult(
                    success=False,
                    error=str(result),
                )
                all_success = False
                errors.append(
                    f"Step {step.step_id} ({step.agent_name}): {result}"
                )
            else:
                if not result.success:
                    all_success = False
                    if result.error:
                        errors.append(
                            f"Step {step.step_id} ({step.agent_name}): "
                            f"{result.error}"
                        )
                if result.output:
                    outputs.append(result.output)
                agents_used.append(step.agent_name)

        combined_output = "\n\n".join(outputs) if outputs else ""

        return PipelineResult(
            success=all_success,
            steps=list(plan.steps),
            final_output=combined_output,
            errors=errors,
            agents_used=agents_used,
        )

    # ── Step runner ──────────────────────────────────────────────────────

    async def _run_step(
        self,
        step: ExecutionStep,
        session_id: str,
        prior_results: dict[int, str] | None = None,
    ) -> AgentResult:
        """Execute a single step by dispatching to its target agent.

        Builds an :class:`AgentContext` with context snapshot and
        optional prior-step outputs, then calls ``agent.run()``.
        """
        agent = self._registry.get(step.agent_name)
        if agent is None:
            logger.error("Agent not found: %s", step.agent_name)
            step.status = StepStatus.FAILED
            result = AgentResult(
                success=False,
                error=f"Agent '{step.agent_name}' is not registered",
            )
            step.result = result
            return result

        # Build enriched context for the sub-agent
        snapshot = self._context.build_snapshot(session_id)
        metadata: dict[str, Any] = {
            "routed_by": "supervisor",
            "target": step.agent_name,
            "step_id": step.step_id,
        }
        if prior_results:
            metadata["prior_step_outputs"] = prior_results

        ctx = AgentContext(
            session_id=session_id,
            intent=step.intent,
            parameters=step.parameters,
            conversation_history=snapshot.get("conversation", []),
            system_state=snapshot.get("system", {}),
            metadata=metadata,
        )

        step.status = StepStatus.RUNNING
        logger.info(
            "▶ Step %d → %s: %.80s",
            step.step_id, step.agent_name, step.intent,
        )

        try:
            result = await agent.run(ctx)
        except Exception as exc:
            logger.exception(
                "Step %d (%s) raised an unhandled exception",
                step.step_id, step.agent_name,
            )
            result = AgentResult(success=False, error=str(exc))

        step.status = (
            StepStatus.COMPLETED if result.success else StepStatus.FAILED
        )
        step.result = result

        logger.info(
            "◀ Step %d → %s | %s | %.0f ms",
            step.step_id,
            step.agent_name,
            "OK" if result.success else "FAIL",
            result.duration_ms,
        )
        return result
