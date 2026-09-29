"""Tests for the NEXUS Supervisor / Orchestrator.

Covers all layers of the orchestration stack:
* Routing strategies  — keyword, capability
* Execution planner   — single / multi-agent plans
* Plan executor       — single / sequential / parallel execution
* SupervisorAgent     — full integration flow
"""

from __future__ import annotations

import pytest

from agents.base import BaseAgent
from agents.registry import AgentRegistry
from agents.supervisor import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    IntentClassification,
    StepStatus,
    SubIntent,
    SupervisorAgent,
)
from agents.supervisor.executor import PlanExecutor
from agents.supervisor.planner import ExecutionPlanner
from agents.supervisor.strategies import (
    AgentMeta,
    CapabilityRoutingStrategy,
    KeywordRoutingStrategy,
)
from agents.types import AgentContext, AgentResult, Capability
from context.manager import ContextManager
from core.types import ModelResponse


# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════


class StubAgent(BaseAgent):
    """Minimal agent for tests — returns a canned response."""

    def __init__(
        self,
        name: str,
        response: str = "ok",
        *,
        success: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            description=f"Stub {name}",
            capabilities=[
                Capability(name=f"{name}_cap", description="stub"),
            ],
        )
        self._response = response
        self._success = success

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            success=self._success,
            output=self._response,
        )


class StubLLMProvider:
    """Satisfies the LLMProvider protocol with canned responses."""

    def __init__(self, content: str = "Hello from LLM") -> None:
        self._content = content

    async def chat(self, messages, tools=None, **kwargs):
        return ModelResponse(content=self._content)


def make_registry(*agents: BaseAgent) -> AgentRegistry:
    """Create a registry pre-loaded with the given agents."""
    registry = AgentRegistry()
    for a in agents:
        registry.register(a)
    return registry


# Standard agent metas used across strategy tests
AGENT_METAS = [
    AgentMeta(
        name="file_agent",
        description="File ops",
        capabilities=["file_read", "file_write", "file_search"],
    ),
    AgentMeta(
        name="system_agent",
        description="System info",
        capabilities=["system_cpu", "system_memory", "system_disk"],
    ),
    AgentMeta(
        name="app_agent",
        description="App mgmt",
        capabilities=["app_open", "app_close", "app_list"],
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# Keyword Routing Strategy
# ═══════════════════════════════════════════════════════════════════════════


class TestKeywordRoutingStrategy:
    """Tests for the keyword-based routing strategy."""

    @pytest.mark.asyncio
    async def test_routes_file_intent(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("find all PDF files", AGENT_METAS)
        assert result.primary_agent == "file_agent"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_routes_system_intent(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("show me cpu usage", AGENT_METAS)
        assert result.primary_agent == "system_agent"

    @pytest.mark.asyncio
    async def test_routes_app_intent(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("launch firefox", AGENT_METAS)
        assert result.primary_agent == "app_agent"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify(
            "what is the meaning of life", AGENT_METAS,
        )
        assert result.primary_agent is None

    @pytest.mark.asyncio
    async def test_unregistered_agent_not_selected(self):
        """Keywords may match but the agent isn't in the available list."""
        strategy = KeywordRoutingStrategy()
        limited = [AgentMeta(name="file_agent", description="Files")]
        result = await strategy.classify(
            "show cpu usage and memory info", limited,
        )
        # system_agent keywords match, but it's not available
        assert result.primary_agent is None or result.primary_agent == "file_agent"

    @pytest.mark.asyncio
    async def test_preserves_raw_intent(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("read my notes.txt", AGENT_METAS)
        assert result.raw_intent == "read my notes.txt"

    @pytest.mark.asyncio
    async def test_scores_are_populated(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("read file and show cpu", AGENT_METAS)
        assert len(result.agent_scores) >= 1

    @pytest.mark.asyncio
    async def test_custom_keywords(self):
        custom = {"file_agent": ["read", "write"]}
        strategy = KeywordRoutingStrategy(keywords=custom)
        result = await strategy.classify("please read this", AGENT_METAS)
        assert result.primary_agent == "file_agent"

    @pytest.mark.asyncio
    async def test_metadata_contains_strategy_name(self):
        strategy = KeywordRoutingStrategy()
        result = await strategy.classify("open a file", AGENT_METAS)
        assert result.metadata.get("strategy") == "keyword"


# ═══════════════════════════════════════════════════════════════════════════
# Capability Routing Strategy
# ═══════════════════════════════════════════════════════════════════════════


class TestCapabilityRoutingStrategy:
    """Tests for capability-based routing."""

    @pytest.mark.asyncio
    async def test_matches_file_capability(self):
        strategy = CapabilityRoutingStrategy()
        result = await strategy.classify("read this file", AGENT_METAS)
        assert result.primary_agent == "file_agent"

    @pytest.mark.asyncio
    async def test_matches_system_capability(self):
        strategy = CapabilityRoutingStrategy()
        result = await strategy.classify("check cpu load", AGENT_METAS)
        assert result.primary_agent == "system_agent"

    @pytest.mark.asyncio
    async def test_matches_app_capability(self):
        strategy = CapabilityRoutingStrategy()
        result = await strategy.classify("open the app", AGENT_METAS)
        assert result.primary_agent == "app_agent"

    @pytest.mark.asyncio
    async def test_no_capability_match(self):
        strategy = CapabilityRoutingStrategy()
        result = await strategy.classify("hello world", AGENT_METAS)
        assert result.primary_agent is None

    @pytest.mark.asyncio
    async def test_metadata_contains_strategy_name(self):
        strategy = CapabilityRoutingStrategy()
        result = await strategy.classify("read file", AGENT_METAS)
        assert result.metadata.get("strategy") == "capability"


# ═══════════════════════════════════════════════════════════════════════════
# Execution Planner
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionPlanner:
    """Tests for the execution planner."""

    def test_single_agent_plan(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(
            raw_intent="read file.txt",
            primary_agent="file_agent",
            confidence=0.8,
        )
        plan = planner.build_plan(classification, "session1")

        assert plan.mode == ExecutionMode.SINGLE
        assert len(plan.steps) == 1
        assert plan.steps[0].agent_name == "file_agent"
        assert plan.steps[0].intent == "read file.txt"
        assert plan.classification is classification

    def test_no_agent_produces_empty_plan(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(raw_intent="what is life")
        plan = planner.build_plan(classification, "session1")

        assert plan.mode == ExecutionMode.SINGLE
        assert len(plan.steps) == 0

    def test_multi_agent_sequential_plan(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(
            raw_intent="check disk and then find large files",
            primary_agent="system_agent",
            requires_multi_agent=True,
            sub_intents=[
                SubIntent(
                    description="check disk space",
                    target_agent="system_agent",
                ),
                SubIntent(
                    description="find large files",
                    target_agent="file_agent",
                    depends_on=[0],
                ),
            ],
        )
        plan = planner.build_plan(classification, "session1")

        assert plan.mode == ExecutionMode.SEQUENTIAL
        assert len(plan.steps) == 2
        assert plan.steps[0].agent_name == "system_agent"
        assert plan.steps[1].agent_name == "file_agent"
        assert plan.steps[1].depends_on == [0]

    def test_multi_agent_parallel_plan(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(
            raw_intent="show cpu and list apps",
            primary_agent="system_agent",
            requires_multi_agent=True,
            sub_intents=[
                SubIntent(
                    description="show cpu",
                    target_agent="system_agent",
                ),
                SubIntent(
                    description="list apps",
                    target_agent="app_agent",
                ),
            ],
        )
        plan = planner.build_plan(classification, "session1")

        assert plan.mode == ExecutionMode.PARALLEL
        assert len(plan.steps) == 2

    def test_plan_has_generated_id(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(
            raw_intent="test",
            primary_agent="file_agent",
        )
        plan = planner.build_plan(classification, "s1")
        assert plan.plan_id  # non-empty

    def test_original_intent_preserved(self):
        planner = ExecutionPlanner()
        classification = IntentClassification(
            raw_intent="read notes.txt",
            primary_agent="file_agent",
        )
        plan = planner.build_plan(classification, "s1")
        assert plan.original_intent == "read notes.txt"


# ═══════════════════════════════════════════════════════════════════════════
# Plan Executor
# ═══════════════════════════════════════════════════════════════════════════


class TestPlanExecutor:
    """Tests for plan execution — single, sequential, and parallel."""

    @pytest.mark.asyncio
    async def test_single_step_success(self):
        registry = make_registry(StubAgent("file_agent", "file contents"))
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="file_agent",
                    intent="read file",
                ),
            ],
            original_intent="read file",
        )
        result = await executor.execute(plan, "session1")

        assert result.success is True
        assert result.final_output == "file contents"
        assert result.agents_used == ["file_agent"]
        assert result.total_duration_ms > 0

    @pytest.mark.asyncio
    async def test_single_step_agent_not_found(self):
        registry = make_registry()  # empty
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="ghost_agent",
                    intent="boo",
                ),
            ],
        )
        result = await executor.execute(plan, "session1")

        assert result.success is False
        assert "not registered" in result.errors[0]

    @pytest.mark.asyncio
    async def test_empty_plan_fails(self):
        registry = make_registry()
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(mode=ExecutionMode.SINGLE, steps=[])
        result = await executor.execute(plan, "session1")

        assert result.success is False
        assert "Empty plan" in result.errors[0]

    @pytest.mark.asyncio
    async def test_sequential_pipeline(self):
        registry = make_registry(
            StubAgent("system_agent", "disk ok"),
            StubAgent("file_agent", "found 3 files"),
        )
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.SEQUENTIAL,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="system_agent",
                    intent="check disk",
                ),
                ExecutionStep(
                    step_id=1,
                    agent_name="file_agent",
                    intent="find files",
                    depends_on=[0],
                ),
            ],
        )
        result = await executor.execute(plan, "session1")

        assert result.success is True
        assert result.final_output == "found 3 files"
        assert "system_agent" in result.agents_used
        assert "file_agent" in result.agents_used

    @pytest.mark.asyncio
    async def test_sequential_skips_on_dependency_failure(self):
        registry = make_registry(
            StubAgent("system_agent", "error", success=False),
            StubAgent("file_agent", "files"),
        )
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.SEQUENTIAL,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="system_agent",
                    intent="check disk",
                ),
                ExecutionStep(
                    step_id=1,
                    agent_name="file_agent",
                    intent="find files",
                    depends_on=[0],
                ),
            ],
        )
        result = await executor.execute(plan, "session1")

        assert result.success is False
        assert plan.steps[1].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        registry = make_registry(
            StubAgent("system_agent", "cpu: 50%"),
            StubAgent("app_agent", "3 apps running"),
        )
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.PARALLEL,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="system_agent",
                    intent="show cpu",
                ),
                ExecutionStep(
                    step_id=1,
                    agent_name="app_agent",
                    intent="list apps",
                ),
            ],
        )
        result = await executor.execute(plan, "session1")

        assert result.success is True
        assert "cpu: 50%" in result.final_output
        assert "3 apps running" in result.final_output
        assert len(result.agents_used) == 2

    @pytest.mark.asyncio
    async def test_parallel_partial_failure(self):
        registry = make_registry(
            StubAgent("system_agent", "cpu ok"),
            StubAgent("app_agent", "failed", success=False),
        )
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.PARALLEL,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="system_agent",
                    intent="cpu",
                ),
                ExecutionStep(
                    step_id=1,
                    agent_name="app_agent",
                    intent="apps",
                ),
            ],
        )
        result = await executor.execute(plan, "session1")

        assert result.success is False
        # system_agent output should still be present
        assert "cpu ok" in result.final_output

    @pytest.mark.asyncio
    async def test_step_status_updated(self):
        registry = make_registry(StubAgent("file_agent", "ok"))
        context = ContextManager()
        executor = PlanExecutor(registry, context)

        plan = ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            steps=[
                ExecutionStep(
                    step_id=0,
                    agent_name="file_agent",
                    intent="read",
                ),
            ],
        )
        await executor.execute(plan, "s1")

        assert plan.steps[0].status == StepStatus.COMPLETED
        assert plan.steps[0].result is not None
        assert plan.steps[0].result.success is True


# ═══════════════════════════════════════════════════════════════════════════
# Supervisor Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestSupervisorAgent:
    """End-to-end tests for the Supervisor orchestrator."""

    @pytest.mark.asyncio
    async def test_routes_to_file_agent(self):
        file_agent = StubAgent("file_agent", "read ok")
        registry = make_registry(file_agent)
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        ctx = AgentContext(intent="read my file.txt", session_id="s1")
        result = await supervisor.run(ctx)

        assert result.success is True
        assert result.output == "read ok"
        assert result.data.get("agent_used") == "file_agent"

    @pytest.mark.asyncio
    async def test_routes_to_system_agent(self):
        sys_agent = StubAgent("system_agent", "cpu ok")
        registry = make_registry(sys_agent)
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        ctx = AgentContext(intent="show cpu usage", session_id="s1")
        result = await supervisor.run(ctx)

        assert result.success is True
        assert result.data.get("agent_used") == "system_agent"

    @pytest.mark.asyncio
    async def test_routes_to_app_agent(self):
        app_agent = StubAgent("app_agent", "launched")
        registry = make_registry(app_agent)
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        ctx = AgentContext(intent="launch firefox", session_id="s1")
        result = await supervisor.run(ctx)

        assert result.success is True
        assert result.data.get("agent_used") == "app_agent"

    @pytest.mark.asyncio
    async def test_unmatched_intent_falls_back_to_llm(self):
        registry = make_registry(StubAgent("file_agent"))
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)
        supervisor.set_llm(StubLLMProvider("I can help with files"))

        ctx = AgentContext(
            intent="what is quantum physics",
            session_id="s1",
        )
        result = await supervisor.run(ctx)

        assert result.success is True
        assert "I can help" in result.output
        assert result.data.get("agent_used") == "supervisor"

    @pytest.mark.asyncio
    async def test_unmatched_intent_without_llm_returns_error(self):
        registry = make_registry(StubAgent("file_agent"))
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)
        # No LLM set → _handle_general will fail

        ctx = AgentContext(
            intent="what is quantum physics",
            session_id="s1",
        )
        result = await supervisor.run(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_strategy_can_be_swapped_at_runtime(self):
        file_agent = StubAgent("file_agent", "from file")
        # Give it a capability the CapabilityStrategy can match
        file_agent.capabilities = [
            Capability(name="file_read", description="Read files"),
        ]
        registry = make_registry(file_agent)
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        # Default keyword strategy
        ctx = AgentContext(intent="read file", session_id="s1")
        result = await supervisor.run(ctx)
        assert result.data.get("agent_used") == "file_agent"

        # Swap to capability strategy
        from agents.supervisor.strategies import CapabilityRoutingStrategy

        supervisor.set_routing_strategy(CapabilityRoutingStrategy())

        ctx2 = AgentContext(intent="read the file please", session_id="s1")
        result2 = await supervisor.run(ctx2)
        # "read" + "file" matches file_read capability
        assert result2.data.get("agent_used") == "file_agent"

    @pytest.mark.asyncio
    async def test_records_conversation_context(self):
        registry = make_registry(StubAgent("file_agent", "done"))
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        ctx = AgentContext(intent="list my files", session_id="s1")
        await supervisor.run(ctx)

        history = context.get_history("s1")
        roles = [m["role"] for m in history]
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_execution_mode_in_result_data(self):
        registry = make_registry(StubAgent("file_agent", "ok"))
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        ctx = AgentContext(intent="find my files", session_id="s1")
        result = await supervisor.run(ctx)

        assert result.data.get("execution_mode") == "single"

    def test_list_agents(self):
        registry = make_registry(
            StubAgent("file_agent"),
            StubAgent("system_agent"),
        )
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        agents = supervisor.list_agents()
        names = [a["name"] for a in agents]
        assert "file_agent" in names
        assert "system_agent" in names

    def test_initialize_and_shutdown(self):
        registry = make_registry(StubAgent("file_agent"))
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        # Should not raise
        supervisor.initialize()
        supervisor.shutdown()

    def test_routing_strategy_property(self):
        registry = make_registry()
        context = ContextManager()
        supervisor = SupervisorAgent(registry, context)

        assert isinstance(supervisor.routing_strategy, KeywordRoutingStrategy)
