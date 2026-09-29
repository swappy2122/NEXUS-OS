"""Tests for the NEXUS OS Testing CLI."""

import io
import json
from contextlib import redirect_stdout
import pytest

from cli import (
    format_structured_response,
    run_single_command,
)
from core.nexus import NexusCore, NexusResponse
from agents.types import ToolCallRecord
from models.dev_backend import DevModelBackend


@pytest.fixture
def core():
    """Create a bootstrapped NexusCore instance."""
    return NexusCore.bootstrap(use_dev_model=True, log_level="WARNING")


def test_format_structured_response_success():
    """Test ASCII box formatting for successful responses."""
    resp = NexusResponse(
        success=True,
        intent="cpu",
        session_id="test_sess",
        task_id="task_123",
        agent_used="system_agent",
        agents_used=["system_agent"],
        execution_mode="single",
        output="CPU: 10% load",
        error=None,
        tool_calls=[
            ToolCallRecord(
                tool_name="system_cpu",
                arguments={"per_cpu": False},
                success=True,
                output={"cpu_percent": 10},
                duration_ms=1.5,
            )
        ],
        duration_ms=5.0,
    )
    formatted = format_structured_response(resp)
    assert "[SUCCESS]" in formatted
    assert "task_123" in formatted
    assert "system_cpu" in formatted
    assert "CLI → NEXUS Core → Supervisor" in formatted
    assert "CPU: 10% load" in formatted


def test_format_structured_response_error():
    """Test ASCII box formatting for error responses."""
    resp = NexusResponse(
        success=False,
        intent="read missing.txt",
        session_id="test_sess",
        task_id="task_fail",
        agent_used="file_agent",
        agents_used=["file_agent"],
        execution_mode="single",
        output="",
        error="File missing.txt not found",
        tool_calls=[
            ToolCallRecord(
                tool_name="file_read",
                arguments={"path": "missing.txt"},
                success=False,
                error="File missing.txt not found",
                duration_ms=0.5,
            )
        ],
        duration_ms=2.0,
    )
    formatted = format_structured_response(resp)
    assert "[ERROR]" in formatted
    assert "task_fail" in formatted
    assert "File missing.txt not found" in formatted
    assert "file_read" in formatted


@pytest.mark.asyncio
async def test_run_single_command_success(core: NexusCore):
    """Test running a single command non-interactively."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = await run_single_command(core, "cpu", output_json=False)

    assert code == 0
    output = buf.getvalue()
    assert "[SUCCESS]" in output
    assert "system_cpu" in output


@pytest.mark.asyncio
async def test_run_single_command_error(core: NexusCore):
    """Test running a failing command returns code 1."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = await run_single_command(core, "read definitely_absent_file.txt", output_json=False)

    assert code == 1
    output = buf.getvalue()
    assert "[ERROR]" in output


@pytest.mark.asyncio
async def test_run_single_command_json_output(core: NexusCore):
    """Test running a command with --json output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = await run_single_command(core, "memory", output_json=True)

    assert code == 0
    raw_json = buf.getvalue()
    data = json.loads(raw_json)
    assert data["status"] == "success"
    assert data["agent_used"] == "system_agent"
    assert data["intent"] == "memory"
    assert len(data["tool_calls"]) >= 1
    assert data["tool_calls"][0]["tool"] == "system_memory"


@pytest.mark.asyncio
async def test_dev_backend_intent_matching():
    """Test DevModelBackend matching for various commands."""
    backend = DevModelBackend()
    tools = [
        {"function": {"name": "system_cpu", "parameters": {}}},
        {"function": {"name": "system_memory", "parameters": {}}},
        {"function": {"name": "file_read", "parameters": {}}},
        {"function": {"name": "file_write", "parameters": {}}},
        {"function": {"name": "app_list_running", "parameters": {}}},
    ]

    # CPU
    resp = await backend.chat([{"role": "user", "content": "check cpu usage"}], tools=tools)
    assert resp.tool_calls[0]["name"] == "system_cpu"

    # File Read
    resp = await backend.chat([{"role": "user", "content": "read /tmp/test.txt"}], tools=tools)
    assert resp.tool_calls[0]["name"] == "file_read"
    assert resp.tool_calls[0]["arguments"]["path"] == "/tmp/test.txt"

    # Direct tool syntax
    resp = await backend.chat([{"role": "user", "content": "file_read path=/tmp/foo.txt"}], tools=tools)
    assert resp.tool_calls[0]["name"] == "file_read"
    assert resp.tool_calls[0]["arguments"]["path"] == "/tmp/foo.txt"
