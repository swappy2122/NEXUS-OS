"""FastAPI application factory for NEXUS OS.

Creates and configures the FastAPI app with all routes, middleware,
and CORS settings.  The actual service wiring (agents, tools, models)
is done in ``main.py`` and stored on ``app.state``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.connection_manager import ConnectionManager
from api.routes import chat, agents, system, vr, vr_state
from core.constants import SYSTEM_NAME, VERSION
from core.event_bus import EventBus
from security.sessions import SessionManager
from vr.window_registry import WindowRegistry

if TYPE_CHECKING:
    from agents.supervisor import SupervisorAgent
    from context.manager import ContextManager
    from core.config import Config
    from models.router import ModelRouter
    from tools.registry import ToolRegistry
    from security.permissions import PermissionGate


def create_app(
    *,
    supervisor: SupervisorAgent,
    context: ContextManager,
    tool_registry: ToolRegistry,
    model_router: ModelRouter,
    config: Config,
    session_manager: SessionManager | None = None,
    event_bus: EventBus | None = None,
    window_registry: WindowRegistry | None = None,
    permission_gate: PermissionGate | None = None,
) -> FastAPI:
    """Build and return a fully configured FastAPI application.

    All shared services are attached to ``app.state`` so that route
    handlers can access them via dependency injection (see
    ``api/dependencies.py``).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan — initialize on startup, cleanup on shutdown."""
        supervisor.initialize()
        await app.state.vr_connections.start()
        try:
            yield
        finally:
            await app.state.vr_connections.stop()
            supervisor.shutdown()

    app = FastAPI(
        title=SYSTEM_NAME,
        version=VERSION,
        description="AI-first VR operating environment — API layer",
        lifespan=lifespan,
    )

    # -- attach shared state -----------------------------------------------
    app.state.supervisor = supervisor
    app.state.context = context
    app.state.tool_registry = tool_registry
    app.state.model_router = model_router
    app.state.config = config
    app.state.session_manager = session_manager or SessionManager(
        lifetime_seconds=config.session_lifetime_seconds,
    )
    app.state.event_bus = event_bus or EventBus()
    app.state.vr_connections = ConnectionManager(app.state.event_bus)
    app.state.window_registry = window_registry or WindowRegistry()
    app.state.permission_gate = permission_gate

    # -- CORS (permissive for development) ---------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- register route modules --------------------------------------------
    app.include_router(chat.router)
    app.include_router(agents.router)
    app.include_router(system.router)
    app.include_router(vr.router)
    app.include_router(vr_state.router)

    @app.get("/", include_in_schema=False)
    async def root():
        """Redirect root path to interactive Swagger documentation."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/docs")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Handle browser favicon request to avoid 404/CORB warnings."""
        from fastapi import Response
        return Response(status_code=204)

    return app
