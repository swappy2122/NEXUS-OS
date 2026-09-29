"""Agent and tool introspection endpoints for NEXUS OS."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.supervisor import SupervisorAgent
from api.dependencies import get_supervisor, get_tool_registry
from api.schemas import (
    AgentInfo,
    AgentListResponse,
    ToolInfo,
    ToolListResponse,
)
from tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1", tags=["introspection"])


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    supervisor: SupervisorAgent = Depends(get_supervisor),
) -> AgentListResponse:
    """List all registered specialized agents."""
    agents = []
    for a in supervisor.list_agents():
        agents.append(
            AgentInfo(
                name=a.get("name", ""),
                role=a.get("name", ""),  # use name as role in new framework
                description=a.get("description", ""),
            )
        )
    return AgentListResponse(agents=agents)


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    registry: ToolRegistry = Depends(get_tool_registry),
) -> ToolListResponse:
    """List all registered tools with their schemas."""
    tools = []
    for t in registry.list_tools():
        tools.append(
            ToolInfo(
                name=t.name,
                description=t.description,
                parameters=t.parameters_schema,
                required_permissions=t.required_permissions,
            )
        )
    return ToolListResponse(tools=tools)
