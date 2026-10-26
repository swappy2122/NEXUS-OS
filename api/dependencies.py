"""FastAPI dependency injection providers for NEXUS OS.

These callables are used with ``Depends()`` in route handlers to
inject shared services (supervisor, context, config, etc.) without
global imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from security.sessions import (
    AuthenticatedSession,
    InvalidSessionToken,
    SessionManager,
)


bearer_scheme = HTTPBearer(auto_error=False)

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


def get_session_manager(request: Request) -> SessionManager:
    """Retrieve the process-local session manager from app state."""
    return request.app.state.session_manager


def get_authenticated_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    sessions: SessionManager = Depends(get_session_manager),
) -> AuthenticatedSession:
    """Resolve a bearer token into an authenticated session identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return sessions.resolve(credentials.credentials)
    except InvalidSessionToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
