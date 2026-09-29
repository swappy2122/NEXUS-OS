"""NEXUS OS — Application Entry Point.

Bootstraps the entire multi-agent system in dependency order:

    Core → Security → Tools → Models → Context → Agents → API

Run with:
    python main.py
    # or
    uvicorn main:app --reload
"""

from __future__ import annotations

from pathlib import Path

import uvicorn

from agents.app_agent import AppAgent
from agents.file_agent import FileAgent
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.system_agent import SystemAgent
from api.server import create_app
from context.manager import ContextManager
from core.config import Config
from core.constants import VERSION
from core.event_bus import EventBus
from core.logger import setup_logger
from models.ollama_backend import OllamaBackend
from models.router import ModelRouter
from security.audit import AuditLog
from security.permissions import PermissionGate
from security.policy import DEFAULT_POLICIES
from tools.app_tools import AppCloseTool, AppIsRunningTool, AppListInstalledTool, AppListRunningTool, AppOpenTool
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


def bootstrap():
    """Wire all components and return a FastAPI application."""

    # ── 1. Core ──────────────────────────────────────────────────────────
    config = Config.load_from_toml(Path("nexus.toml"))
    logger = setup_logger(level=config.log_level)
    event_bus = EventBus()

    logger.info("NEXUS OS v%s starting up (env=%s)", VERSION, config.env)

    # ── 2. Security ──────────────────────────────────────────────────────
    permission_gate = PermissionGate(DEFAULT_POLICIES)
    audit_log = AuditLog(event_bus)

    # ── 3. Tools (system-wide registry for permission gating) ────────────
    tool_registry = ToolRegistry(permission_gate, event_bus)

    file_read = FileReadTool()
    file_write = FileWriteTool()
    file_search = FileSearchTool()
    file_metadata = FileMetadataTool()
    file_open_os = FileOpenOSTool()
    file_mkdir = FileMkdirTool()
    file_move = FileMoveTool()
    file_delete = FileDeleteTool()

    process_run = ProcessRunTool()

    system_info = SystemInfoTool()
    system_cpu = SystemCpuTool()
    system_memory = SystemMemoryTool()
    system_disk = SystemDiskTool()
    system_os = SystemOsTool()
    system_processes = SystemProcessesTool()

    app_list_installed = AppListInstalledTool()
    app_list_running = AppListRunningTool()
    app_is_running = AppIsRunningTool()
    app_open = AppOpenTool()
    app_close = AppCloseTool()

    all_tools = [
        file_read, file_write, file_search, file_metadata,
        file_open_os, file_mkdir, file_move, file_delete,
        process_run,
        system_info, system_cpu, system_memory, system_disk, system_os, system_processes,
        app_list_installed, app_list_running, app_is_running, app_open, app_close,
    ]
    for t in all_tools:
        tool_registry.register(t)

    # ── 4. Models ────────────────────────────────────────────────────────
    model_router = ModelRouter()
    ollama = OllamaBackend(
        model_id=config.default_model,
        base_url=config.ollama_base_url,
    )
    model_router.register_backend(ollama)
    model_router.set_route("*", "ollama")

    # ── 5. Context ───────────────────────────────────────────────────────
    context = ContextManager()

    # ── 6. Agents ────────────────────────────────────────────────────────
    #   a) Create agents
    file_agent = FileAgent()
    system_agent = SystemAgent()
    app_agent = AppAgent()

    #   b) Register tools ON each agent (agent-owned toolbox)
    file_agent.register_tools([
        file_read, file_write, file_search, file_metadata,
        file_open_os, file_mkdir, file_move, file_delete,
    ])
    system_agent.register_tools([
        system_info, system_cpu, system_memory, system_disk, system_os, system_processes, process_run,
    ])
    app_agent.register_tools([app_list_installed, app_list_running, app_is_running, app_open, app_close])

    #   c) Inject LLM provider (ModelRouter satisfies LLMProvider protocol)
    file_agent.set_llm(model_router)
    system_agent.set_llm(model_router)
    app_agent.set_llm(model_router)

    #   d) Build agent registry
    agent_registry = AgentRegistry()
    agent_registry.register(file_agent)
    agent_registry.register(system_agent)
    agent_registry.register(app_agent)

    #   e) Create supervisor
    supervisor = SupervisorAgent(agent_registry, context)
    supervisor.set_llm(model_router)

    # ── 7. API ───────────────────────────────────────────────────────────
    app = create_app(
        supervisor=supervisor,
        context=context,
        tool_registry=tool_registry,
        model_router=model_router,
        config=config,
    )

    logger.info(
        "Bootstrap complete: %d agents, %d tools",
        len(agent_registry),
        len(tool_registry.list_tools()),
    )

    return app


# Create the app at module level so uvicorn can find it
app = bootstrap()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
