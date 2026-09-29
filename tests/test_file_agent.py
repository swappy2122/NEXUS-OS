"""Unit tests for NEXUS FileAgent and File Management Tools."""

import tempfile
import unittest
from pathlib import Path
from typing import Any

from agents.file_agent import FileAgent
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.types import AgentContext
from context.manager import ContextManager
from models.router import ModelResponse
from tools.file_tools import (
    FileDeleteTool,
    FileMetadataTool,
    FileMkdirTool,
    FileMoveTool,
    FileOpenOSTool,
    FileReadTool,
    FileSearchTool,
    FileWriteTool,
    create_directory,
    get_file_metadata,
    move_file,
    validate_safe_path,
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


class TestFileToolsAndAgent(unittest.IsolatedAsyncioTestCase):
    """Test suite for FileAgent and filesystem tools."""

    # ── Path Security Validation Tests ──────────────────────────────────

    def test_validate_safe_path_valid(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            p = validate_safe_path(tmp.name)
            self.assertTrue(p.exists())

    def test_validate_safe_path_restricted(self) -> None:
        with self.assertRaises(PermissionError):
            validate_safe_path("/etc/passwd")

        with self.assertRaises(PermissionError):
            validate_safe_path("/sys/kernel")

    # ── Safe Helper Functions Tests ──────────────────────────────────────

    def test_get_file_metadata(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
            tmp.write(b"Hello NEXUS OS")
            tmp.flush()
            meta = get_file_metadata(tmp.name)
            self.assertTrue(meta["is_file"])
            self.assertEqual(meta["extension"], ".txt")
            self.assertGreater(meta["size_bytes"], 0)

    def test_create_directory_and_move_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir) / "test_subdir"
            res = create_directory(str(dir_path))
            self.assertTrue(res["created"])
            self.assertTrue(dir_path.is_dir())

            # Create file and move it
            src = dir_path / "file1.txt"
            src.write_text("sample content")
            dst = dir_path / "file2_moved.txt"

            move_res = move_file(str(src), str(dst))
            self.assertTrue(move_res["moved"])
            self.assertFalse(src.exists())
            self.assertTrue(dst.exists())

    # ── BaseTool Classes Execution Tests ────────────────────────────────

    async def test_file_search_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc1.py").write_text("# py 1")
            (Path(tmpdir) / "doc2.txt").write_text("text 2")

            tool = FileSearchTool()
            result = await tool.execute(path=tmpdir, pattern="*.py")
            self.assertTrue(result.success)
            self.assertEqual(len(result.output), 1)

    async def test_file_metadata_tool(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            tool = FileMetadataTool()
            result = await tool.execute(path=tmp.name)
            self.assertTrue(result.success)
            self.assertEqual(result.output["path"], str(Path(tmp.name).resolve()))

    async def test_file_mkdir_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "new_folder"
            tool = FileMkdirTool()
            result = await tool.execute(path=str(target))
            self.assertTrue(result.success)
            self.assertTrue(target.is_dir())

    async def test_file_move_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "a.txt"
            dst = Path(tmpdir) / "b.txt"
            src.write_text("data")

            tool = FileMoveTool()
            result = await tool.execute(src_path=str(src), dst_path=str(dst))
            self.assertTrue(result.success)
            self.assertTrue(dst.exists())

    # ── FileAgent Tests ─────────────────────────────────────────────────

    def test_file_agent_capabilities(self) -> None:
        agent = FileAgent()
        self.assertEqual(agent.name, "file_agent")
        cap_names = [c.name for c in agent.capabilities]
        self.assertIn("file_search", cap_names)
        self.assertIn("file_metadata", cap_names)
        self.assertIn("file_open_os", cap_names)
        self.assertIn("file_mkdir", cap_names)
        self.assertIn("file_move", cap_names)

    async def test_file_agent_execution_with_mock_llm(self) -> None:
        agent = FileAgent()
        agent.register_tools([FileSearchTool(), FileMetadataTool()])
        mock_llm = MockLLMProvider(
            response_content="Found files.",
            tool_calls=[{
                "name": "file_search",
                "arguments": {"path": ".", "pattern": "*.py"},
            }],
        )
        agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_file_1",
            session_id="session_1",
            intent="Search for Python files in current directory",
        )

        result = await agent.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(len(agent._tool_call_log), 1)

    async def test_supervisor_routes_to_file_agent(self) -> None:
        agent = FileAgent()
        registry = AgentRegistry()
        registry.register(agent)

        context = ContextManager()
        supervisor = SupervisorAgent(agent_registry=registry, context=context)

        mock_llm = MockLLMProvider(response_content="File agent handled.")
        supervisor.set_llm(mock_llm)
        agent.set_llm(mock_llm)

        ctx = AgentContext(
            task_id="task_file_2",
            session_id="session_1",
            intent="Find files matching *.txt in folder",
        )

        result = await supervisor.run(ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("agent_used"), "file_agent")


if __name__ == "__main__":
    unittest.main()
