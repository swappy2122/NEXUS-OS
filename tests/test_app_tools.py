"""Unit tests for Linux Application Management Tools & Safe Functions."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tools.app_tools import (
    AppCloseTool,
    AppIsRunningTool,
    AppListInstalledTool,
    AppListRunningTool,
    AppOpenTool,
    is_application_running,
    launch_application,
    list_installed_applications,
    list_running_applications,
    parse_desktop_file,
    terminate_application,
    validate_app_name,
    validate_arguments,
    resolve_app_or_folder_command,
)


class TestAppToolsAndFunctions(unittest.IsolatedAsyncioTestCase):
    """Test suite for application management functions and tools."""

    # ── Validation Tests ────────────────────────────────────────────────

    def test_validate_app_name_valid(self) -> None:
        self.assertEqual(validate_app_name("firefox"), "firefox")
        self.assertEqual(validate_app_name("/usr/bin/vlc"), "/usr/bin/vlc")

    def test_validate_app_name_invalid(self) -> None:
        with self.assertRaises(ValueError):
            validate_app_name("")

        with self.assertRaises(ValueError):
            validate_app_name("firefox; rm -rf /")

        with self.assertRaises(ValueError):
            validate_app_name("vlc & background")

    def test_validate_arguments_valid(self) -> None:
        self.assertEqual(validate_arguments(["--incognito", "http://example.com"]), ["--incognito", "http://example.com"])
        self.assertEqual(validate_arguments(None), [])

    def test_validate_arguments_invalid(self) -> None:
        with self.assertRaises(ValueError):
            validate_arguments("not a list")  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            validate_arguments(["arg1", "\x00invalid"])

    # ── Core OS Safe Functions Tests ────────────────────────────────────

    async def test_list_installed_applications(self) -> None:
        apps = await list_installed_applications()
        self.assertIsInstance(apps, list)

    async def test_list_running_applications(self) -> None:
        procs = await list_running_applications()
        self.assertIsInstance(procs, list)
        self.assertGreater(len(procs), 0)
        pids = [p["pid"] for p in procs]
        self.assertIn(os.getpid(), pids)

    async def test_is_application_running_by_pid(self) -> None:
        current_pid = os.getpid()
        status = await is_application_running(pid=current_pid)
        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], current_pid)

    async def test_is_application_running_by_name(self) -> None:
        status = await is_application_running(app_name="python")
        self.assertTrue(status["running"])
        self.assertGreater(len(status["matching_pids"]), 0)

    async def test_launch_and_terminate_application(self) -> None:
        # Launch python process sleeping for 10s without shell=True
        launch_res = await launch_application(
            app_name=sys.executable,
            arguments=["-c", "import time; time.sleep(10)"],
        )
        self.assertIn("pid", launch_res)
        pid = launch_res["pid"]
        self.assertIsInstance(pid, int)

        # Check process is running
        status = await is_application_running(pid=pid)
        self.assertTrue(status["running"])

        # Terminate process
        term_res = await terminate_application(pid=pid)
        self.assertTrue(term_res["success"])
        self.assertIn(pid, term_res["terminated_pids"])

    async def test_launch_nonexistent_application(self) -> None:
        with self.assertRaises(FileNotFoundError):
            await launch_application("nonexistent_binary_xyz_999")

    # ── Tool Class Wrappers Tests ───────────────────────────────────────

    async def test_app_list_installed_tool(self) -> None:
        tool = AppListInstalledTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("applications", result.output)

    async def test_app_list_running_tool(self) -> None:
        tool = AppListRunningTool()
        result = await tool.execute()
        self.assertTrue(result.success)
        self.assertIn("processes", result.output)

    async def test_app_is_running_tool(self) -> None:
        tool = AppIsRunningTool()
        result = await tool.execute(pid=os.getpid())
        self.assertTrue(result.success)
        self.assertTrue(result.output["running"])

    async def test_app_open_tool_invalid(self) -> None:
        tool = AppOpenTool()
        result = await tool.execute(app_name="invalid; command")
        self.assertFalse(result.success)
        self.assertIn("Invalid character", result.error)

    async def test_app_close_tool_no_args(self) -> None:
        tool = AppCloseTool()
        result = await tool.execute()
        self.assertFalse(result.success)

    def test_resolve_app_or_folder_command_files(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("files")
        self.assertTrue(exec_path.endswith("gio") or exec_path.endswith("xdg-open"))
        self.assertIn(str(Path.home()), args)
        self.assertEqual(display, "Files")

    def test_resolve_app_or_folder_command_file_manager(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("file manager")
        self.assertTrue(exec_path.endswith("gio") or exec_path.endswith("xdg-open"))
        self.assertIn(str(Path.home()), args)
        self.assertEqual(display, "Files")

    def test_resolve_app_or_folder_command_home(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("home")
        self.assertTrue(exec_path.endswith("gio") or exec_path.endswith("xdg-open"))
        self.assertIn(str(Path.home()), args)
        self.assertEqual(display, "Files")

    def test_resolve_app_or_folder_command_downloads(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("downloads")
        self.assertTrue(exec_path.endswith("gio") or exec_path.endswith("xdg-open"))
        self.assertIn(str(Path.home() / "Downloads"), args)
        self.assertEqual(display, "Downloads")

    def test_resolve_app_or_folder_command_documents(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("documents")
        self.assertTrue(exec_path.endswith("gio") or exec_path.endswith("xdg-open"))
        self.assertIn(str(Path.home() / "Documents"), args)
        self.assertEqual(display, "Documents")

    def test_resolve_app_or_folder_command_firefox(self) -> None:
        exec_path, args, display = resolve_app_or_folder_command("Firefox")
        self.assertTrue(exec_path.endswith("firefox"))
        self.assertEqual(args, [])

    def test_resolve_app_or_folder_nonexistent_folder(self) -> None:
        with self.assertRaises(FileNotFoundError):
            resolve_app_or_folder_command("/nonexistent_folder_xyz_123")


if __name__ == "__main__":
    unittest.main()
