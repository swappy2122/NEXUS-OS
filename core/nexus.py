"""NEXUS Core — Central Operating System Kernel & Orchestrator.

Routes commands through:
    Caller (CLI / API) → NEXUS Core → Supervisor → Agent → Tool

Manages the lifecycle, registries, security policies, context,
and model routing for all components in the NEXUS OS architecture.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.app_agent import AppAgent
from agents.file_agent import FileAgent
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.system_agent import SystemAgent
from agents.types import AgentContext, ToolCallRecord
from context.manager import ContextManager
from core.config import Config
from core.constants import SYSTEM_NAME, VERSION
from core.event_bus import EventBus
from core.logger import setup_logger
from models.dev_backend import DevModelBackend
from models.router import ModelRouter
from security.audit import AuditLog
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES
from tools.app_tools import (
    AppCloseTool,
    AppIsRunningTool,
    AppListInstalledTool,
    AppListRunningTool,
    AppOpenTool,
)
from tools.file_tools import (
    FileDeleteTool,
    FileMetadataTool,
    FileMkdirTool,
    FileMoveTool,
    FileOpenOSTool,
    FileReadTool,
    FileSearchTool,
    FileWriteTool,
)
from tools.process_tools import ProcessRunTool
from tools.registry import ToolRegistry
from tools.system_tools import (
    SystemCpuTool,
    SystemDiskTool,
    SystemInfoTool,
    SystemMemoryTool,
    SystemOsTool,
    SystemProcessesTool,
)

logger = logging.getLogger("nexus.core")


@dataclass
class NexusResponse:
    """Structured response returned by NEXUS Core after command execution."""

    success: bool
    intent: str
    session_id: str
    task_id: str
    agent_used: str
    agents_used: list[str]
    execution_mode: str
    output: str
    error: str | None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def route_display(self) -> str:
        """Formatted representation of the execution path."""
        agent_part = ", ".join(self.agents_used) if self.agents_used else self.agent_used
        tools_part = (
            ", ".join(tc.tool_name for tc in self.tool_calls)
            if self.tool_calls
            else "direct"
        )
        return f"CLI → NEXUS Core → Supervisor → [{agent_part}] → [{tools_part}]"

    def to_dict(self) -> dict[str, Any]:
        """Convert response to a serializable dictionary."""
        return {
            "status": "success" if self.success else "error",
            "task_id": self.task_id,
            "session_id": self.session_id,
            "intent": self.intent,
            "route": self.route_display,
            "agent_used": self.agent_used,
            "agents_used": self.agents_used,
            "execution_mode": self.execution_mode,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "error": self.error,
            "tool_calls": [
                {
                    "tool": tc.tool_name,
                    "arguments": tc.arguments,
                    "success": tc.success,
                    "output": tc.output,
                    "error": tc.error,
                    "duration_ms": round(tc.duration_ms, 2),
                }
                for tc in self.tool_calls
            ],
            "timestamp": self.timestamp.isoformat(),
        }


class NexusCore:
    """The central kernel and execution engine of NEXUS OS.

    Coordinates all core subsystems:
    1. Config & EventBus
    2. Security & Audit Logging
    3. ToolRegistry & Agent-owned Toolboxes
    4. ModelRouter (with DevModelBackend for zero-LLM testing)
    5. ContextManager
    6. AgentRegistry (File, System, App agents)
    7. SupervisorAgent (Orchestrator)
    """

    def __init__(
        self,
        config: Config,
        event_bus: EventBus,
        permission_gate: PermissionGate,
        audit_log: AuditLog,
        tool_registry: ToolRegistry,
        model_router: ModelRouter,
        context_manager: ContextManager,
        agent_registry: AgentRegistry,
        supervisor: SupervisorAgent,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.permission_gate = permission_gate
        self.audit_log = audit_log
        self.tool_registry = tool_registry
        self.model_router = model_router
        self.context_manager = context_manager
        self.agent_registry = agent_registry
        self.supervisor = supervisor
        self.start_time = datetime.now(timezone.utc)
        self._is_running = True

    @classmethod
    def bootstrap(
        cls,
        config_path: Path | str | None = None,
        use_dev_model: bool = True,
        log_level: str | None = None,
    ) -> NexusCore:
        """Bootstrap and wire all NEXUS OS components in dependency order.

        Parameters:
            config_path: Path to nexus.toml (optional).
            use_dev_model: If True, uses the deterministic DevModelBackend
                           which requires no external LLM.
            log_level: Optional log level override (e.g. 'warning', 'info').
        """
        # 1. Core Config & Event Bus
        cfg_file = Path(config_path) if config_path else Path("nexus.toml")
        config = Config.load_from_toml(cfg_file) if cfg_file.exists() else Config()
        effective_level = log_level or config.log_level
        setup_logger(level=effective_level)
        event_bus = EventBus()

        logger.info("Initializing %s v%s (env=%s)", SYSTEM_NAME, VERSION, config.env)

        # 2. Security Gate & Audit Log
        permission_gate = PermissionGate(DEFAULT_POLICIES)
        audit_log = AuditLog(event_bus)

        # 3. Tool Registry & Instantiation
        tool_registry = ToolRegistry(permission_gate, event_bus)

        # Instantiate file tools
        file_tools = [
            FileReadTool(),
            FileWriteTool(),
            FileSearchTool(),
            FileMetadataTool(),
            FileOpenOSTool(),
            FileMkdirTool(),
            FileMoveTool(),
            FileDeleteTool(),
        ]

        # Instantiate system & process tools
        system_tools = [
            SystemInfoTool(),
            SystemCpuTool(),
            SystemMemoryTool(),
            SystemDiskTool(),
            SystemOsTool(),
            SystemProcessesTool(),
            ProcessRunTool(),
        ]

        # Instantiate app tools
        app_tools = [
            AppListInstalledTool(),
            AppListRunningTool(),
            AppIsRunningTool(),
            AppOpenTool(),
            AppCloseTool(),
        ]

        # Register tools in system registry
        for tool in file_tools + system_tools + app_tools:
            tool_registry.register(tool)

        # 4. Models Layer
        model_router = ModelRouter()
        if use_dev_model:
            dev_backend = DevModelBackend()
            model_router.register_backend(dev_backend)
            model_router.set_route("*", dev_backend.name)
            logger.info("DevModelBackend registered (zero-LLM testing mode)")

        # 5. Context Manager
        context_manager = ContextManager()

        # 6. Agents
        file_agent = FileAgent()
        file_agent.register_tools(file_tools)
        file_agent.set_llm(model_router)

        system_agent = SystemAgent()
        system_agent.register_tools(system_tools)
        system_agent.set_llm(model_router)

        app_agent = AppAgent()
        app_agent.register_tools(app_tools)
        app_agent.set_llm(model_router)

        agent_registry = AgentRegistry()
        agent_registry.register(file_agent)
        agent_registry.register(system_agent)
        agent_registry.register(app_agent)

        # 7. Supervisor Agent
        supervisor = SupervisorAgent(agent_registry, context_manager)
        supervisor.set_llm(model_router)

        core = cls(
            config=config,
            event_bus=event_bus,
            permission_gate=permission_gate,
            audit_log=audit_log,
            tool_registry=tool_registry,
            model_router=model_router,
            context_manager=context_manager,
            agent_registry=agent_registry,
            supervisor=supervisor,
        )

        logger.info(
            "NEXUS Core bootstrap complete: %d agents, %d tools",
            len(agent_registry),
            len(tool_registry.list_tools()),
        )
        return core

    async def execute(
        self,
        intent: str,
        session_id: str = "cli_session",
    ) -> NexusResponse:
        """Route a command through the NEXUS OS processing pipeline:

            CLI → NEXUS Core → Supervisor → Agent → Tool

        Parameters:
            intent: Natural language or direct command entered by the user.
            session_id: Session identifier for context tracking.

        Returns:
            A structured :class:`NexusResponse`.
        """
        logger.debug("NexusCore executing intent: %s (session=%s)", intent, session_id)

        # Create AgentContext for Supervisor
        ctx = AgentContext(
            session_id=session_id,
            intent=intent,
        )

        # Run through Supervisor
        agent_result = await self.supervisor.run(ctx)

        # Determine agent and route information
        agent_used = agent_result.data.get("agent_used", agent_result.agent_name or "supervisor")
        agents_used = agent_result.data.get("agents_used", [agent_used])
        execution_mode = agent_result.data.get("execution_mode", "single")
        tool_calls = agent_result.tool_calls_made

        # Determine overall success considering agent and tool results
        has_tool_failure = any(not tc.success for tc in tool_calls)
        overall_success = agent_result.success and not has_tool_failure and not agent_result.error
        error_msg = agent_result.error
        if not error_msg and has_tool_failure:
            failed_tools = [tc for tc in tool_calls if not tc.success]
            error_msg = "; ".join(f"Tool '{t.tool_name}' failed: {t.error}" for t in failed_tools)

        response = NexusResponse(
            success=overall_success,
            intent=intent,
            session_id=session_id,
            task_id=ctx.task_id,
            agent_used=agent_used,
            agents_used=agents_used,
            execution_mode=execution_mode,
            output=agent_result.output,
            error=error_msg,
            tool_calls=tool_calls,
            duration_ms=round(agent_result.duration_ms, 2),
        )

        # Publish event for audit and subscribers
        await self.event_bus.publish(
            "nexus.command.executed",
            {
                "task_id": response.task_id,
                "session_id": response.session_id,
                "success": response.success,
                "agent_used": response.agent_used,
                "tool_calls_count": len(tool_calls),
                "duration_ms": response.duration_ms,
            },
        )

        return response

    # ── Introspection & Diagnostics ──────────────────────────────────────

    def get_system_status(self) -> dict[str, Any]:
        """Return diagnostic status information about NEXUS Core."""
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        return {
            "system_name": SYSTEM_NAME,
            "version": VERSION,
            "uptime_seconds": round(uptime, 1),
            "environment": self.config.env,
            "agents_registered": len(self.agent_registry),
            "tools_registered": len(self.tool_registry.list_tools()),
            "routing_strategy": type(self.supervisor.routing_strategy).__name__,
        }

    def get_agents(self) -> list[dict[str, Any]]:
        """Return metadata for all registered agents."""
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "capabilities": [c.name for c in agent.capabilities],
                "tools": list(agent.tools.keys()),
            }
            for agent in self.agent_registry
        ]

    def get_tools(self) -> list[dict[str, Any]]:
        """Return metadata for all registered tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "required_permissions": tool.required_permissions,
            }
            for tool in self.tool_registry.list_tools()
        ]

    def get_history(self, session_id: str = "cli_session") -> list[dict[str, str]]:
        """Return conversation messages for the given session."""
        return self.context_manager.get_history(session_id)
