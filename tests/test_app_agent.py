"""Unit tests for NEXUS AppAgent."""

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agents.app_agent import AppAgent
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.types import AgentContext, AgentResult, Capability
from context.manager import ContextManager
from models.router import ModelResponse
from tools.app_tools import AppCloseTool, AppListInstalledTool, AppListRunningTool, AppOpenTool


class MockLLMProvider:
    """Mock LLM provider for testing agents without network calls."""

    def __init__(self, response_content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.response_content = response_content
        self.tool_calls = tool_calls or []

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ModelResponse:
        return ModelResponse(
            content=self.response_content,
            tool_calls=self.tool_calls,
            model="mock_model",
        )


class TestAppAgent(unittest.IsolatedAsyncioTestCase):
    """Test suite for AppAgent."""

    def setUp(self) -> None:
        self.agent = AppAgent()
        self.installed_tool = AppListInstalledTool()
        self.running_tool = AppListRunningTool()
        self.open_tool = AppOpenTool()
        self.close_tool = AppCloseTool()

        self.agent.register_tools([
            self.installed_tool,
            self.running_tool,
            self.open_tool,
            self.close_tool,
        ])

    def test_app_agent_metadata(self) -> None:
        self.assertEqual(self.agent.name, "app_agent")
        self.assertIn("application", self.agent.description.lower())
        cap_names = [c.name for c in self.agent.capabilities]
        self.assertIn("app_list", cap_names)
        self.assertIn("app_open", cap_names)
        self.assertIn("app_close", cap_names)

    async def test_app_agent_direct_llm_response(self) -> None:
        mock_llm = MockLLMProvider(response_content="Installed applications: Firefox, Calculator.")
        self.agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_1",
            session_id="session_1",
            intent="List installed apps",
        )

        result = await self.agent.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.output, "Installed applications: Firefox, Calculator.")

    async def test_app_agent_tool_execution(self) -> None:
        # Mock LLM requesting app_list_running tool
        mock_llm = MockLLMProvider(
            response_content="Let me check running apps.",
            tool_calls=[{
                "name": "app_list_running",
                "arguments": {"filter": "python"},
            }],
        )
        self.agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_2",
            session_id="session_1",
            intent="What python processes are running?",
        )

        result = await self.agent.run(ctx)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.output)
        self.assertEqual(len(self.agent._tool_call_log), 1)
        self.assertEqual(self.agent._tool_call_log[0].tool_name, "app_list_running")

    async def test_supervisor_routes_to_app_agent(self) -> None:
        registry = AgentRegistry()
        registry.register(self.agent)

        context = ContextManager()
        supervisor = SupervisorAgent(agent_registry=registry, context=context)

        mock_llm = MockLLMProvider(response_content="Opened firefox successfully.")
        supervisor.set_llm(mock_llm)
        self.agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_3",
            session_id="session_1",
            intent="Please open app firefox",
        )

        result = await supervisor.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("agent_used"), "app_agent")


if __name__ == "__main__":
    unittest.main()
