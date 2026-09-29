"""Chat endpoint for NEXUS OS.

This is the primary interface for frontends to communicate with the
multi-agent system.  A user message comes in, the Supervisor routes
it, and a response comes back.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.supervisor import SupervisorAgent
from agents.types import AgentContext
from api.dependencies import get_supervisor
from api.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    supervisor: SupervisorAgent = Depends(get_supervisor),
) -> ChatResponse:
    """Send a message and receive an agent-processed response.

    The Supervisor classifies the intent, routes to the appropriate
    specialized agent, and returns the result.
    """
    ctx = AgentContext(
        session_id=request.session_id,
        intent=request.message,
    )

    result = await supervisor.run(ctx)

    return ChatResponse(
        task_id=ctx.task_id,
        status="completed" if result.success else "failed",
        result=result.output,
        error=result.error,
        agent_used=result.data.get("agent_used", result.agent_name),
        duration_ms=round(result.duration_ms, 1),
    )
