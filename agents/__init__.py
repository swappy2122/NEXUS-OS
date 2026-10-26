"""NEXUS OS Agent Framework.

Public API::

    from agents import BaseAgent, AgentContext, AgentResult, Capability
    from agents import AgentRegistry, SupervisorAgent
    from agents import AgentError, LLMProvider
    from agents import WindowAgent
"""

from agents.app_agent import AppAgent
from agents.base import BaseAgent, LLMProvider
from agents.window_agent import WindowAgent
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.types import AgentContext, AgentError, AgentResult, Capability, ToolCallRecord

__all__ = [
    "BaseAgent",
    "LLMProvider",
    "AgentRegistry",
    "SupervisorAgent",
    "AgentContext",
    "AgentError",
    "AgentResult",
    "Capability",
    "ToolCallRecord",
    "AppAgent",
    "WindowAgent",
]
