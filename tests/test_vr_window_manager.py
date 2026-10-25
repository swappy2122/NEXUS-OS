"""Unit and integration tests for NEXUS VR Window Manager.

Tests the full lifecycle of VR windows without AI:
- window creation
- movement
- resizing
- rotation
- selection/focus
- close
- layout snapping
- VR event reconciliation
- permission-gated window tools
"""

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agents.vr_bridge import VRBridgeClient
from agents.window_agent import WindowAgent
from agents.window_layout import WindowLayoutEngine
from agents.window_state_store import WindowStateStore
from core.vr_types import (
    Quaternion3D,
    Vector3D,
    WindowCommand,
    WindowCommandType,
    WindowContentType,
    WindowEvent,
    WindowEventType,
    WindowLayoutMode,
    WindowSize,
    WindowState,
)
from tools.window_tools import (
    WindowCloseTool,
    WindowCreateTool,
    WindowFocusTool,
    WindowListTool,
    WindowMoveTool,
    WindowResizeTool,
    WindowRotateTool,
    WindowSnapLayoutTool,
    create_window_tools,
)
from agents.types import AgentContext


class TestWindowStateStore(unittest.TestCase):
    """Test suite for WindowStateStore CRUD and focus management."""

    def setUp(self) -> None:
        self.store = WindowStateStore()

    def test_window_create(self) -> None:
        """Verify window creation with unique ID, default z-order, and timestamp."""
        state = WindowState(
            title="Terminal",
            position=Vector3D(x=0.0, y=1.5, z=2.0),
            size=WindowSize(width=1.0, height=0.8),
            content_type=WindowContentType.TERMINAL,
        )
        created = self.store.create(state)
        self.assertEqual(created.title, "Terminal")
        self.assertEqual(created.z_order, 1)
        self.assertIsNotNone(created.created_at)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get(created.window_id), created)

    def test_duplicate_window_rejection(self) -> None:
        """Verify creating a window with existing ID raises ValueError."""
        state = WindowState(window_id="win-1", title="First")
        self.store.create(state)
        duplicate = WindowState(window_id="win-1", title="Second")
        with self.assertRaises(ValueError):
            self.store.create(duplicate)

    def test_window_move(self) -> None:
        """Verify window movement updates position."""
        state = self.store.create(WindowState(title="Editor"))
        new_pos = Vector3D(x=1.2, y=1.8, z=3.0)
        updated = self.store.update(state.window_id, position=new_pos)
        self.assertEqual(updated.position, new_pos)
        self.assertEqual(self.store.get(state.window_id).position, new_pos)

    def test_window_resize(self) -> None:
        """Verify window resizing updates width and height."""
        state = self.store.create(WindowState(title="Browser"))
        new_size = WindowSize(width=1.6, height=1.0)
        updated = self.store.update(state.window_id, size=new_size)
        self.assertEqual(updated.size.width, 1.6)
        self.assertEqual(updated.size.height, 1.0)

    def test_window_rotate(self) -> None:
        """Verify window rotation updates quaternion."""
        state = self.store.create(WindowState(title="Viewer"))
        new_rot = Quaternion3D.from_euler(yaw_deg=45.0)
        updated = self.store.update(state.window_id, rotation=new_rot)
        self.assertAlmostEqual(updated.rotation.w, new_rot.w, places=4)
        self.assertAlmostEqual(updated.rotation.y, new_rot.y, places=4)

    def test_window_selection_and_focus(self) -> None:
        """Verify focus transitions: focusing a window unfocuses the prior window and brings it to front."""
        w1 = self.store.create(WindowState(title="Window 1"))
        w2 = self.store.create(WindowState(title="Window 2"))

        # Focus w1
        self.store.set_focus(w1.window_id)
        self.assertTrue(self.store.get(w1.window_id).is_focused)
        self.assertEqual(self.store.get_focused().window_id, w1.window_id)

        # Focus w2
        self.store.set_focus(w2.window_id)
        self.assertFalse(self.store.get(w1.window_id).is_focused)
        self.assertTrue(self.store.get(w2.window_id).is_focused)
        self.assertEqual(self.store.get_focused().window_id, w2.window_id)
        self.assertGreater(self.store.get(w2.window_id).z_order, self.store.get(w1.window_id).z_order)

    def test_window_close(self) -> None:
        """Verify window closing removes it and clears focus if focused."""
        w1 = self.store.create(WindowState(title="To Close"))
        self.store.set_focus(w1.window_id)
        self.assertEqual(self.store.count(), 1)

        closed = self.store.remove(w1.window_id)
        self.assertTrue(closed)
        self.assertEqual(self.store.count(), 0)
        self.assertIsNone(self.store.get(w1.window_id))
        self.assertIsNone(self.store.get_focused())

    def test_workspace_and_app_queries(self) -> None:
        """Verify filtering windows by workspace and app_id."""
        self.store.create(WindowState(title="W1", workspace_id="ws_a", app_id="app_1"))
        self.store.create(WindowState(title="W2", workspace_id="ws_a", app_id="app_2"))
        self.store.create(WindowState(title="W3", workspace_id="ws_b", app_id="app_1"))

        ws_a_windows = self.store.get_by_workspace("ws_a")
        self.assertEqual(len(ws_a_windows), 2)
        app_1_windows = self.store.get_by_app("app_1")
        self.assertEqual(len(app_1_windows), 2)


class TestWindowLayoutEngine(unittest.TestCase):
    """Test suite for spatial layout computation."""

    def setUp(self) -> None:
        self.engine = WindowLayoutEngine()

    def test_curved_arc_positions(self) -> None:
        """Verify curved arc layout places multiple windows evenly at target radius."""
        windows = [
            WindowState(window_id="w1", title="1"),
            WindowState(window_id="w2", title="2"),
            WindowState(window_id="w3", title="3"),
        ]
        positions = self.engine.compute_positions(
            windows,
            WindowLayoutMode.CURVED_ARC,
            user_position=Vector3D.zero(),
            user_forward=Vector3D.forward(),
        )
        self.assertEqual(len(positions), 3)
        # Center window should be close to center (x ~ 0)
        self.assertAlmostEqual(positions["w2"].x, 0.0, delta=0.1)
        # Left window should have negative x, right positive x
        self.assertLess(positions["w1"].x, 0.0)
        self.assertGreater(positions["w3"].x, 0.0)

    def test_flat_grid_positions(self) -> None:
        """Verify flat grid arrangement."""
        windows = [WindowState(window_id=f"w{i}", title=str(i)) for i in range(4)]
        positions = self.engine.compute_positions(
            windows,
            WindowLayoutMode.FLAT_GRID,
            user_position=Vector3D.zero(),
            user_forward=Vector3D.forward(),
        )
        self.assertEqual(len(positions), 4)
        for pos in positions.values():
            self.assertGreater(pos.z, 0.0)


class TestWindowAgent(unittest.IsolatedAsyncioTestCase):
    """Test suite for WindowAgent deterministic execution and public APIs (No AI)."""

    def setUp(self) -> None:
        self.store = WindowStateStore()
        self.bridge = MagicMock(spec=VRBridgeClient)
        self.bridge.send_command = AsyncMock()
        self.agent = WindowAgent(state_store=self.store, bridge=self.bridge)

    async def test_create_window_programmatic(self) -> None:
        """Verify programmatic create_window updates store and sends command."""
        w = await self.agent.create_window(
            title="Code Editor",
            position=Vector3D(x=0.0, y=1.5, z=2.0),
            size=WindowSize(width=1.2, height=0.9),
            content_type=WindowContentType.TEXT_EDITOR,
        )
        self.assertEqual(w.title, "Code Editor")
        self.assertTrue(w.is_focused)
        self.assertEqual(self.store.count(), 1)
        self.bridge.send_command.assert_awaited_once()
        cmd = self.bridge.send_command.call_args[0][0]
        self.assertEqual(cmd.command_type, WindowCommandType.CREATE)
        self.assertEqual(cmd.window_id, w.window_id)

    async def test_move_window_programmatic(self) -> None:
        """Verify programmatic move_window."""
        w = await self.agent.create_window(title="Move Target")
        new_pos = Vector3D(x=0.5, y=1.6, z=2.8)
        updated = await self.agent.move_window(position=new_pos, window_id=w.window_id)
        self.assertEqual(updated.position, new_pos)
        last_cmd = self.bridge.send_command.call_args[0][0]
        self.assertEqual(last_cmd.command_type, WindowCommandType.MOVE)

    async def test_resize_window_programmatic(self) -> None:
        """Verify programmatic resize_window."""
        w = await self.agent.create_window(title="Resize Target")
        new_size = WindowSize(width=1.8, height=1.2)
        updated = await self.agent.resize_window(size=new_size, window_id=w.window_id)
        self.assertEqual(updated.size.width, 1.8)
        last_cmd = self.bridge.send_command.call_args[0][0]
        self.assertEqual(last_cmd.command_type, WindowCommandType.RESIZE)

    async def test_rotate_window_programmatic(self) -> None:
        """Verify programmatic rotate_window."""
        w = await self.agent.create_window(title="Rotate Target")
        rot = Quaternion3D.from_euler(yaw_deg=30.0)
        updated = await self.agent.rotate_window(rotation=rot, window_id=w.window_id)
        self.assertAlmostEqual(updated.rotation.w, rot.w, places=4)
        last_cmd = self.bridge.send_command.call_args[0][0]
        self.assertEqual(last_cmd.command_type, WindowCommandType.ROTATE)

    async def test_focus_window_programmatic(self) -> None:
        """Verify programmatic focus_window."""
        w1 = await self.agent.create_window(title="Window A")
        w2 = await self.agent.create_window(title="Window B")
        self.assertEqual(self.store.get_focused().window_id, w2.window_id)

        focused = await self.agent.focus_window(window_id=w1.window_id)
        self.assertEqual(focused.window_id, w1.window_id)
        self.assertTrue(w1.is_focused)
        self.assertFalse(self.store.get(w2.window_id).is_focused)

    async def test_close_window_programmatic(self) -> None:
        """Verify programmatic close_window."""
        w = await self.agent.create_window(title="Close Me")
        closed = await self.agent.close_window(window_id=w.window_id)
        self.assertTrue(closed)
        self.assertEqual(self.store.count(), 0)
        last_cmd = self.bridge.send_command.call_args[0][0]
        self.assertEqual(last_cmd.command_type, WindowCommandType.CLOSE)

    async def test_execute_deterministic_actions(self) -> None:
        """Verify execute() dispatches structured actions deterministically without AI."""
        # 1. Create action
        res_create = await self.agent.execute(AgentContext(
            intent="create a new window",
            parameters={"action": "create", "title": "Direct Window"},
        ))
        self.assertTrue(res_create.success)
        win_id = res_create.data["window_id"]

        # 2. Move action
        res_move = await self.agent.execute(AgentContext(
            intent="move window",
            parameters={"action": "move", "window_id": win_id, "position": {"x": 1.0, "y": 1.5, "z": 2.0}},
        ))
        self.assertTrue(res_move.success)

        # 3. Resize action
        res_resize = await self.agent.execute(AgentContext(
            intent="resize window",
            parameters={"action": "resize", "window_id": win_id, "size": {"width": 1.4, "height": 0.9}},
        ))
        self.assertTrue(res_resize.success)

        # 4. Rotate action
        res_rotate = await self.agent.execute(AgentContext(
            intent="rotate window",
            parameters={"action": "rotate", "window_id": win_id, "rotation": {"x": 0.0, "y": 0.38268, "z": 0.0, "w": 0.92388}},
        ))
        self.assertTrue(res_rotate.success)

        # 5. Focus action
        res_focus = await self.agent.execute(AgentContext(
            intent="focus window",
            parameters={"action": "focus", "window_id": win_id},
        ))
        self.assertTrue(res_focus.success)

        # 6. List action
        res_list = await self.agent.execute(AgentContext(
            intent="list open windows",
            parameters={"action": "list"},
        ))
        self.assertTrue(res_list.success)
        self.assertEqual(res_list.data["window_count"], 1)

        # 7. Close action
        res_close = await self.agent.execute(AgentContext(
            intent="close window",
            parameters={"action": "close", "window_id": win_id},
        ))
        self.assertTrue(res_close.success)
        self.assertEqual(self.store.count(), 0)

    async def test_vr_event_reconciliation(self) -> None:
        """Verify VR shell events from Unity reconcile Python WindowStateStore."""
        w = await self.agent.create_window(title="Interactive Window")

        # Position changed from VR grab
        await self.agent._handle_vr_event(WindowEvent(
            event_type=WindowEventType.POSITION_CHANGED,
            window_id=w.window_id,
            payload={"position": {"x": 0.8, "y": 1.7, "z": 2.2}},
        ))
        self.assertEqual(self.store.get(w.window_id).position.x, 0.8)

        # Size changed from VR handle drag
        await self.agent._handle_vr_event(WindowEvent(
            event_type=WindowEventType.SIZE_CHANGED,
            window_id=w.window_id,
            payload={"size": {"width": 2.0, "height": 1.2}},
        ))
        self.assertEqual(self.store.get(w.window_id).size.width, 2.0)

        # Close request from VR close button
        await self.agent._handle_vr_event(WindowEvent(
            event_type=WindowEventType.INTERACTION_CLOSE_REQUEST,
            window_id=w.window_id,
        ))
        self.assertIsNone(self.store.get(w.window_id))


class TestWindowTools(unittest.IsolatedAsyncioTestCase):
    """Test suite for Window BaseTool implementations."""

    def setUp(self) -> None:
        self.agent = WindowAgent()
        self.tools = create_window_tools(self.agent)
        self.tool_map = {t.name: t for t in self.tools}

    async def test_tools_lifecycle(self) -> None:
        """Verify window tools create, move, resize, rotate, focus, list, snap, and close."""
        # Create
        create_tool = self.tool_map["window_create"]
        res_create = await create_tool.execute(title="Tool Window")
        self.assertTrue(res_create.success)
        win_id = res_create.output["window_id"]

        # Move
        move_tool = self.tool_map["window_move"]
        res_move = await move_tool.execute(window_id=win_id, position={"x": 0.5, "y": 1.5, "z": 2.5})
        self.assertTrue(res_move.success)

        # Resize
        resize_tool = self.tool_map["window_resize"]
        res_resize = await resize_tool.execute(window_id=win_id, size={"width": 1.5, "height": 1.0})
        self.assertTrue(res_resize.success)

        # Rotate
        rotate_tool = self.tool_map["window_rotate"]
        res_rotate = await rotate_tool.execute(window_id=win_id, rotation={"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
        self.assertTrue(res_rotate.success)

        # Focus
        focus_tool = self.tool_map["window_focus"]
        res_focus = await focus_tool.execute(window_id=win_id)
        self.assertTrue(res_focus.success)

        # List
        list_tool = self.tool_map["window_list"]
        res_list = await list_tool.execute()
        self.assertTrue(res_list.success)
        self.assertEqual(len(res_list.output), 1)

        # Snap
        snap_tool = self.tool_map["window_snap"]
        res_snap = await snap_tool.execute(layout="curved_arc")
        self.assertTrue(res_snap.success)

        # Close
        close_tool = self.tool_map["window_close"]
        res_close = await close_tool.execute(window_id=win_id)
        self.assertTrue(res_close.success)
        self.assertEqual(self.agent.store.count(), 0)


if __name__ == "__main__":
    unittest.main()
