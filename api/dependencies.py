"""FastAPI dependency injection providers for NEXUS OS.

These callables are used with ``Depends()`` in route handlers to
inject shared services (supervisor, context, config, etc.) without
global imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from agents.supervisor import SupervisorAgent
    from context.manager import ContextManager
    from core.config import Config
    from models.router import ModelRouter
    from tools.registry import ToolRegistry


def get_supervisor(request: Request) -> SupervisorAgent:
    """Retrieve the Supervisor singleton from app state."""
    return request.app.state.supervisor


def get_context(request: Request) -> ContextManager:
    """Retrieve the ContextManager from app state."""
    return request.app.state.context


def get_tool_registry(request: Request) -> ToolRegistry:
    """Retrieve the ToolRegistry from app state."""
    return request.app.state.tool_registry


def get_model_router(request: Request) -> ModelRouter:
    """Retrieve the ModelRouter from app state."""
    return request.app.state.model_router


def get_config(request: Request) -> Config:
    """Retrieve the Config from app state."""
    return request.app.state.config
