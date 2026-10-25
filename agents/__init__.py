"""NEXUS OS Agent Framework.

Public API::

    from agents import BaseAgent, AgentContext, AgentResult, Capability
    from agents import AgentRegistry, SupervisorAgent
    from agents import AgentError, LLMProvider
    from agents import WindowAgent, WindowStateStore, VRBridgeClient
"""

from agents.app_agent import AppAgent
from agents.base import BaseAgent, LLMProvider
from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.types import AgentContext, AgentError, AgentResult, Capability, ToolCallRecord
from agents.window_agent import WindowAgent
from agents.window_state_store import WindowStateStore
from agents.vr_bridge import VRBridgeClient
from agents.window_layout import WindowLayoutEngine

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
    "WindowStateStore",
    "VRBridgeClient",
    "WindowLayoutEngine",
]
