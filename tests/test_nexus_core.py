"""Tests for NEXUS Core and the CLI → NEXUS Core → Supervisor → Agent → Tool pipeline."""

import tempfile
from pathlib import Path
import pytest

from core.nexus import NexusCore, NexusResponse


@pytest.fixture
def core():
    """Create a bootstrapped NexusCore instance in zero-LLM test mode."""
    return NexusCore.bootstrap(use_dev_model=True, log_level="WARNING")


@pytest.mark.asyncio
async def test_bootstrap_initialization(core: NexusCore):
    """Test that bootstrap properly initializes all subsystems."""
    status = core.get_system_status()
    assert status["agents_registered"] >= 3
    assert status["tools_registered"] >= 15
    assert status["routing_strategy"] in ("LLMRoutingStrategy", "KeywordRoutingStrategy")


@pytest.mark.asyncio
async def test_execute_system_cpu_route(core: NexusCore):
    """Test Route: CLI → NEXUS Core → Supervisor → SystemAgent → SystemCpuTool."""
    response = await core.execute("cpu")
    assert isinstance(response, NexusResponse)
    assert response.success is True
    assert response.agent_used == "system_agent"
    assert "system_cpu" in response.route_display
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].tool_name == "system_cpu"
    assert response.tool_calls[0].success is True
    assert "cpu_model" in response.output or "cpu" in response.output.lower()


@pytest.mark.asyncio
async def test_execute_system_memory_route(core: NexusCore):
    """Test Route: CLI → NEXUS Core → Supervisor → SystemAgent → SystemMemoryTool."""
    response = await core.execute("memory")
    assert response.success is True
    assert response.agent_used == "system_agent"
    assert any(tc.tool_name == "system_memory" for tc in response.tool_calls)
    assert "memory_total" in str(response.tool_calls[0].output)


@pytest.mark.asyncio
async def test_execute_file_search_route(core: NexusCore):
    """Test Route: CLI → NEXUS Core → Supervisor → FileAgent → FileSearchTool."""
    response = await core.execute("search *.toml")
    assert response.success is True
    assert response.agent_used == "file_agent"
    assert any(tc.tool_name == "file_search" for tc in response.tool_calls)


@pytest.mark.asyncio
async def test_execute_file_write_and_read_lifecycle(core: NexusCore):
    """Test file write followed by file read through NEXUS Core pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_lifecycle.txt"

        # 1. Write file
        write_cmd = f"write {test_file} HelloNexusWorld"
        write_res = await core.execute(write_cmd)
        assert write_res.success is True
        assert write_res.agent_used == "file_agent"
        assert any(tc.tool_name == "file_write" for tc in write_res.tool_calls)

        # 2. Read file
        read_cmd = f"read {test_file}"
        read_res = await core.execute(read_cmd)
        assert read_res.success is True
        assert read_res.agent_used == "file_agent"
        assert "HelloNexusWorld" in read_res.output


@pytest.mark.asyncio
async def test_execute_file_read_error_structured_response(core: NexusCore):
    """Test that a missing file returns a structured error response."""
    response = await core.execute("read definitely_non_existent_file_xyz.txt")
    assert response.success is False
    assert response.agent_used == "file_agent"
    assert response.error is not None
    assert "Path does not exist" in response.error
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].success is False


@pytest.mark.asyncio
async def test_execute_multi_agent_parallel_pipeline(core: NexusCore):
    """Test multi-agent command routing: CLI → Core → Supervisor → [SystemAgent, AppAgent]."""
    response = await core.execute("show cpu and list running apps")
    assert response.success is True
    assert response.execution_mode == "parallel"
    assert "system_agent" in response.agents_used
    assert "app_agent" in response.agents_used
    assert len(response.tool_calls) >= 2

    tool_names = [tc.tool_name for tc in response.tool_calls]
    assert "system_cpu" in tool_names
    assert "app_list_running" in tool_names


@pytest.mark.asyncio
async def test_event_bus_publishes_on_execute(core: NexusCore):
    """Test that executing a command publishes an event on EventBus."""
    events_received = []

    async def listener(payload):
        events_received.append(payload)

    core.event_bus.subscribe("nexus.command.executed", listener)
    await core.execute("cpu")

    assert len(events_received) == 1
    assert events_received[0]["agent_used"] == "system_agent"
    assert events_received[0]["success"] is True


@pytest.mark.asyncio
async def test_introspection_methods(core: NexusCore):
    """Test introspection queries on NexusCore."""
    agents = core.get_agents()
    assert len(agents) >= 3
    agent_names = {a["name"] for a in agents}
    assert {"file_agent", "system_agent", "app_agent"}.issubset(agent_names)

    tools = core.get_tools()
    assert len(tools) >= 15
    tool_names = {t["name"] for t in tools}
    assert {"system_cpu", "file_read", "app_list_running"}.issubset(tool_names)
