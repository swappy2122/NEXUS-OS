"""Tests for the NEXUS OS Context Manager, EnvironmentContext, and ReferentResolver."""

import pytest

from context.environment import (
    ActionType,
    AppInfo,
    EnvironmentContext,
    UserAction,
    WindowInfo,
    WorkspaceInfo,
)
from context.referent_resolver import ReferentResolver, ResolutionResult
from context.manager import ContextManager
from core.types import ToolResult


# ══════════════════════════════════════════════════════════════════════════
# EnvironmentContext tests
# ══════════════════════════════════════════════════════════════════════════


class TestWorkspaceTracking:
    def test_set_active_workspace(self):
        env = EnvironmentContext()
        env.update_workspaces([
            WorkspaceInfo(index=0, name="Main", is_active=True),
            WorkspaceInfo(index=1, name="Dev"),
        ])
        assert env.active_workspace.name == "Main"

        env.set_active_workspace(1)
        assert env.active_workspace.name == "Dev"
        assert env.active_workspace.is_active is True

    def test_no_active_workspace(self):
        env = EnvironmentContext()
        assert env.active_workspace is None


class TestFocusedWindow:
    def test_update_focused_window(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox", pid=1234))

        win = WindowInfo(
            window_id="0x1234",
            title="GitHub - Mozilla Firefox",
            app_name="firefox",
            is_focused=True,
        )
        env.update_focused_window(win)

        assert env.focused_window is win
        assert env.focused_window.is_focused is True
        assert env.active_app is not None
        assert env.active_app.name == "firefox"

    def test_focus_change_defocuses_old(self):
        env = EnvironmentContext()
        win1 = WindowInfo(window_id="0x1", title="Window 1", app_name="app1")
        win2 = WindowInfo(window_id="0x2", title="Window 2", app_name="app2")

        env.update_focused_window(win1)
        assert win1.is_focused is True

        env.update_focused_window(win2)
        assert win1.is_focused is False
        assert win2.is_focused is True


class TestRunningApps:
    def test_register_and_get_app(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox", pid=100))
        env.register_app(AppInfo(name="code", pid=200))

        assert env.get_app("firefox") is not None
        assert env.get_app("Firefox") is not None  # case-insensitive
        assert env.get_app("nonexistent") is None
        assert len(env.running_apps) == 2

    def test_unregister_app(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox", pid=100))
        env.unregister_app("firefox")
        assert env.get_app("firefox") is None
        assert len(env.running_apps) == 0

    def test_unregister_clears_active_references(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox", pid=100))
        env.update_focused_window(WindowInfo(
            window_id="0x1", title="Tab", app_name="firefox",
        ))
        assert env.active_app is not None

        env.unregister_app("firefox")
        assert env.active_app is None
        assert env.focused_window is None

    def test_eviction_on_capacity(self):
        env = EnvironmentContext(max_running_apps=3)
        env.register_app(AppInfo(name="app1"))
        env.register_app(AppInfo(name="app2"))
        env.register_app(AppInfo(name="app3"))

        # Fourth app should evict the oldest
        env.register_app(AppInfo(name="app4"))
        assert len(env.running_apps) == 3
        assert env.get_app("app4") is not None

    def test_update_running_apps_bulk(self):
        env = EnvironmentContext()
        env.update_running_apps([
            AppInfo(name="firefox"),
            AppInfo(name="code"),
            AppInfo(name="terminal"),
        ])
        assert len(env.running_apps) == 3
        assert env.get_app("code") is not None


class TestActionRecording:
    def test_record_action(self):
        env = EnvironmentContext()
        env.record(ActionType.OPEN_APP, "firefox", "app")
        env.record(ActionType.FILE_OPERATION, "/home/test.py", "file")

        actions = env.recent_actions
        assert len(actions) == 2
        assert actions[0].subject == "firefox"
        assert actions[1].subject == "/home/test.py"

    def test_bounded_action_history(self):
        env = EnvironmentContext(max_recent_actions=5)
        for i in range(10):
            env.record(ActionType.COMMAND, f"cmd_{i}", "command")

        assert len(env.recent_actions) == 5
        # Oldest should have been evicted
        assert env.recent_actions[0].subject == "cmd_5"

    def test_record_action_with_params(self):
        env = EnvironmentContext()
        env.record(
            ActionType.FILE_OPERATION,
            "/home/test.py",
            "file",
            description="Read test.py",
            encoding="utf-8",
        )
        action = env.recent_actions[-1]
        assert action.parameters["encoding"] == "utf-8"


class TestReferentResolution:
    @pytest.fixture
    def env_with_state(self):
        env = EnvironmentContext()
        # Set up desktop state
        env.register_app(AppInfo(name="firefox", pid=100))
        env.register_app(AppInfo(name="code", pid=200))
        env.update_focused_window(WindowInfo(
            window_id="0x1",
            title="NEXUS OS - Visual Studio Code",
            app_name="code",
        ))
        env.record(ActionType.OPEN_APP, "firefox", "app")
        env.record(ActionType.FILE_OPERATION, "/home/user/project/main.py", "file")
        return env

    def test_resolve_this_to_focused_window(self, env_with_state):
        result = env_with_state.resolve_referent("this")
        assert result is not None
        assert result["source"] == "focused_window"
        assert "Visual Studio Code" in result["subject"]

    def test_resolve_this_with_app_hint(self, env_with_state):
        result = env_with_state.resolve_referent("this", subject_type_hint="app")
        assert result is not None
        assert result["subject_type"] == "app"
        assert result["subject"] == "code"

    def test_resolve_it_to_last_action(self, env_with_state):
        result = env_with_state.resolve_referent("it")
        assert result is not None
        assert result["subject"] == "/home/user/project/main.py"

    def test_resolve_it_with_app_hint(self, env_with_state):
        result = env_with_state.resolve_referent("it", subject_type_hint="app")
        assert result is not None
        assert result["subject"] == "firefox"

    def test_resolve_that_to_second_last(self, env_with_state):
        result = env_with_state.resolve_referent("that")
        assert result is not None
        assert result["subject"] == "firefox"

    def test_resolve_unknown_pronoun_uses_it(self, env_with_state):
        result = env_with_state.resolve_referent("something")
        assert result is not None
        # Falls back to "it" heuristic → last action

    def test_resolve_fails_on_empty_context(self):
        env = EnvironmentContext()
        assert env.resolve_referent("this") is None
        assert env.resolve_referent("it") is None


class TestEnvironmentSnapshot:
    def test_snapshot_compact(self):
        env = EnvironmentContext()
        env.update_workspaces([
            WorkspaceInfo(index=0, name="Main", is_active=True),
        ])
        env.register_app(AppInfo(name="firefox"))
        env.register_app(AppInfo(name="code"))
        env.update_focused_window(WindowInfo(
            window_id="0x1", title="My Tab", app_name="firefox",
        ))
        env.record(ActionType.OPEN_APP, "firefox", "app")

        snap = env.snapshot()
        assert snap["workspace"] == {"index": 0, "name": "Main"}
        assert snap["focused_window"]["title"] == "My Tab"
        assert snap["active_app"] == "firefox"
        assert sorted(snap["running_apps"]) == ["code", "firefox"]
        assert len(snap["recent_actions"]) == 1

    def test_snapshot_empty(self):
        env = EnvironmentContext()
        snap = env.snapshot()
        assert snap == {}

    def test_snapshot_limits_actions(self):
        env = EnvironmentContext()
        for i in range(20):
            env.record(ActionType.COMMAND, f"cmd_{i}", "command")
        snap = env.snapshot(max_actions=5)
        assert len(snap["recent_actions"]) == 5

    def test_clear(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox"))
        env.record(ActionType.OPEN_APP, "firefox", "app")
        env.clear()
        assert env.running_apps == {}
        assert env.recent_actions == []
        assert env.focused_window is None


# ══════════════════════════════════════════════════════════════════════════
# ReferentResolver tests
# ══════════════════════════════════════════════════════════════════════════


class TestReferentResolver:
    @pytest.fixture
    def resolver_with_state(self):
        env = EnvironmentContext()
        env.register_app(AppInfo(name="firefox", pid=100))
        env.update_focused_window(WindowInfo(
            window_id="0x1", title="GitHub", app_name="firefox",
        ))
        env.record(ActionType.OPEN_APP, "firefox", "app")
        return ReferentResolver(env)

    def test_resolve_close_this(self, resolver_with_state):
        result = resolver_with_state.resolve("close this")
        assert "firefox" in result.resolved_intent.lower() or "GitHub" in result.resolved_intent
        assert len(result.referents) == 1
        assert result.referents[0].pronoun == "this"
        assert result.referents[0].confidence > 0

    def test_resolve_move_it_left(self, resolver_with_state):
        result = resolver_with_state.resolve("move it left")
        assert result.referents[0].pronoun == "it"
        assert result.referents[0].resolved != ""

    def test_no_pronouns(self, resolver_with_state):
        result = resolver_with_state.resolve("open firefox")
        assert result.resolved_intent == "open firefox"
        assert result.referents == []

    def test_has_pronouns(self, resolver_with_state):
        assert resolver_with_state.has_pronouns("close this") is True
        assert resolver_with_state.has_pronouns("open firefox") is False

    def test_unresolved_on_empty_context(self):
        env = EnvironmentContext()
        resolver = ReferentResolver(env)
        result = resolver.resolve("close this")
        assert result.has_unresolved is True

    def test_exclude_common_sentences(self):
        """Pronouns followed by auxiliary verbs should not be resolved."""
        env = EnvironmentContext()
        resolver = ReferentResolver(env)
        result = resolver.resolve("is this a good idea?")
        # "this is" should be excluded by the negative lookahead
        # But "this" not followed by "is" at the same position — check
        # the pattern handles "is this" — "this" is still matched since
        # "a good idea" follows, not an auxiliary.  That's fine; it will
        # simply be unresolved.
        # The key test: sentences like "it is fine" should NOT trigger.
        result2 = resolver.resolve("it is fine")
        assert result2.referents == []


# ══════════════════════════════════════════════════════════════════════════
# ContextManager integration tests
# ══════════════════════════════════════════════════════════════════════════


class TestContextManager:
    @pytest.fixture
    def ctx(self):
        return ContextManager()

    def test_conversation_roundtrip(self, ctx):
        ctx.add_message("s1", "user", "hello")
        ctx.add_message("s1", "assistant", "hi")
        history = ctx.get_history("s1")
        assert len(history) == 2
        assert history[0]["content"] == "hello"

    def test_system_state_roundtrip(self, ctx):
        ctx.update_system_state("cwd", "/home/user")
        snap = ctx.get_system_snapshot()
        assert snap["cwd"] == "/home/user"

    def test_tool_result_caching(self, ctx):
        ctx.cache_tool_result(ToolResult(
            tool_name="file_read", success=True, output="contents",
        ))
        snap = ctx.get_system_snapshot()
        assert len(snap["recent_tool_results"]) == 1

    def test_environment_integration(self, ctx):
        ctx.register_app(AppInfo(name="firefox", pid=100))
        ctx.update_focused_window(WindowInfo(
            window_id="0x1", title="Tab", app_name="firefox",
        ))
        ctx.record_action(ActionType.OPEN_APP, "firefox", "app")

        assert ctx.environment.active_app.name == "firefox"
        assert ctx.has_pronouns("close this") is True

    def test_resolve_intent(self, ctx):
        ctx.register_app(AppInfo(name="firefox", pid=100))
        ctx.update_focused_window(WindowInfo(
            window_id="0x1", title="Tab", app_name="firefox",
        ))
        result = ctx.resolve_intent("close this")
        assert "firefox" in result.resolved_intent.lower() or "Tab" in result.resolved_intent

    def test_build_snapshot_includes_environment(self, ctx):
        ctx.add_message("s1", "user", "hello")
        ctx.register_app(AppInfo(name="firefox"))
        ctx.record_action(ActionType.OPEN_APP, "firefox", "app")

        snap = ctx.build_snapshot("s1")
        assert "conversation" in snap
        assert "system" in snap
        assert "environment" in snap
        assert "running_apps" in snap["environment"]
        assert "recent_actions" in snap["environment"]

    def test_workspace_shortcuts(self, ctx):
        ctx.update_workspaces([
            WorkspaceInfo(index=0, name="Main", is_active=True),
            WorkspaceInfo(index=1, name="Dev"),
        ])
        assert ctx.environment.active_workspace.name == "Main"

        ctx.set_active_workspace(1)
        assert ctx.environment.active_workspace.name == "Dev"

    def test_unregister_app_shortcut(self, ctx):
        ctx.register_app(AppInfo(name="firefox"))
        ctx.unregister_app("firefox")
        assert ctx.environment.get_app("firefox") is None

    def test_snapshot_bounded(self, ctx):
        """Snapshot should respect max_env_actions."""
        for i in range(20):
            ctx.record_action(ActionType.COMMAND, f"cmd_{i}", "command")

        snap = ctx.build_snapshot("s1", max_env_actions=3)
        assert len(snap["environment"]["recent_actions"]) == 3
