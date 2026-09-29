"""System endpoints for NEXUS OS — health checks and context inspection."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from api.dependencies import get_config, get_context, get_model_router, get_supervisor, get_tool_registry
from api.schemas import ContextSnapshotResponse, HealthResponse
from context.manager import ContextManager
from core.config import Config
from core.constants import VERSION
from models.router import ModelRouter
from tools.registry import ToolRegistry
from agents.supervisor import SupervisorAgent

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Startup time — set when the module is first imported
_startup_time = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health(
    supervisor: SupervisorAgent = Depends(get_supervisor),
    registry: ToolRegistry = Depends(get_tool_registry),
    model_router: ModelRouter = Depends(get_model_router),
) -> HealthResponse:
    """Return system health and component status."""
    model_status = await model_router.health_check()

    return HealthResponse(
        status="ok",
        version=VERSION,
        uptime_seconds=round(time.monotonic() - _startup_time, 1),
        agents_count=len(supervisor.list_agents()),
        tools_count=len(registry.list_tools()),
        model_backends=model_status,
    )


@router.get("/context/{session_id}", response_model=ContextSnapshotResponse)
async def get_context_snapshot(
    session_id: str,
    context: ContextManager = Depends(get_context),
) -> ContextSnapshotResponse:
    """Inspect the current context state for a session."""
    history = context.get_history(session_id)
    system_state = context.get_system_snapshot()

    return ContextSnapshotResponse(
        session_id=session_id,
        conversation_length=len(history),
        system_state=system_state,
    )
