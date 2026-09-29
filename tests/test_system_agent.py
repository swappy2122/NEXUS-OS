"""Unit tests for NEXUS SystemAgent and Read-Only System Tools."""

import unittest
from typing import Any

from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.system_agent import SystemAgent
from agents.types import AgentContext
from context.manager import ContextManager
from models.router import ModelResponse
from tools.system_tools import (
    SystemCpuTool,
    SystemDiskTool,
    SystemInfoTool,
    SystemMemoryTool,
    SystemOsTool,
    SystemProcessesTool,
    get_cpu_info,
    get_disk_info,
    get_memory_info,
    get_os_info,
    get_running_processes_summary,
)


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


class TestSystemToolsAndAgent(unittest.IsolatedAsyncioTestCase):
    """Test suite for SystemAgent and read-only system tools."""

    # ── Read-Only Helper Functions Tests ─────────────────────────────────

    def test_get_cpu_info(self) -> None:
        info = get_cpu_info()
        self.assertIn("cpu_count_logical", info)
        self.assertGreaterEqual(info["cpu_count_logical"], 1)
        self.assertIn("load_average_1min", info)
        self.assertIn("architecture", info)

    def test_get_memory_info(self) -> None:
        info = get_memory_info()
        self.assertIn("memory_total_bytes", info)
        self.assertIn("memory_used_percent", info)
        self.assertIsInstance(info["memory_used_percent"], float)

    def test_get_disk_info(self) -> None:
        info = get_disk_info("/")
        self.assertEqual(info["path"], "/")
        self.assertIn("total_gb", info)
        self.assertIn("free_gb", info)
        self.assertGreater(info["total_gb"], 0)

    def test_get_os_info(self) -> None:
        info = get_os_info()
        self.assertIn("os_system", info)
        self.assertIn("architecture", info)
        self.assertIn("uptime_hours", info)

    def test_get_running_processes_summary(self) -> None:
        info = get_running_processes_summary()
        self.assertIn("total_running_processes", info)
        self.assertGreater(info["total_running_processes"], 0)
        self.assertIsInstance(info["sample_processes"], list)

    # ── Tool Class Execution Tests ───────────────────────────────────────

    async def test_system_info_tool(self) -> None:
        tool = SystemInfoTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("cpu", result.output)
        self.assertIn("memory", result.output)
        self.assertIn("disk", result.output)
        self.assertIn("os", result.output)

    async def test_system_cpu_tool(self) -> None:
        tool = SystemCpuTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("cpu_count_logical", result.output)

    async def test_system_memory_tool(self) -> None:
        tool = SystemMemoryTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("memory_total_gb", result.output)

    async def test_system_disk_tool(self) -> None:
        tool = SystemDiskTool()
        result = await tool.execute(path="/")
        self.assertTrue(result.success)
        self.assertIn("free_gb", result.output)

    async def test_system_os_tool(self) -> None:
        tool = SystemOsTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("os_system", result.output)

    async def test_system_processes_tool(self) -> None:
        tool = SystemProcessesTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("total_running_processes", result.output)

    # ── SystemAgent Tests ────────────────────────────────────────────────

    def test_system_agent_capabilities(self) -> None:
        agent = SystemAgent()
        self.assertEqual(agent.name, "system_agent")
        cap_names = [c.name for c in agent.capabilities]
        self.assertIn("system_info", cap_names)
        self.assertIn("system_cpu", cap_names)
        self.assertIn("system_memory", cap_names)
        self.assertIn("system_disk", cap_names)
        self.assertIn("system_os", cap_names)
        self.assertIn("system_processes", cap_names)

    async def test_system_agent_execution_with_mock_llm(self) -> None:
        agent = SystemAgent()
        agent.register_tools([SystemCpuTool(), SystemMemoryTool()])
        mock_llm = MockLLMProvider(
            response_content="System metrics reported.",
            tool_calls=[{
                "name": "system_cpu",
                "arguments": {},
            }],
        )
        agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_sys_1",
            session_id="session_1",
            intent="What is the CPU usage and load?",
        )

        result = await agent.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(len(agent._tool_call_log), 1)

    async def test_supervisor_routes_to_system_agent(self) -> None:
        agent = SystemAgent()
        registry = AgentRegistry()
        registry.register(agent)

        context = ContextManager()
        supervisor = SupervisorAgent(agent_registry=registry, context=context)

        mock_llm = MockLLMProvider(response_content="System agent handled monitoring.")
        supervisor.set_llm(mock_llm)
        agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_sys_2",
            session_id="session_1",
            intent="Show system memory and disk usage",
        )

        result = await supervisor.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("agent_used"), "system_agent")


if __name__ == "__main__":
    unittest.main()
