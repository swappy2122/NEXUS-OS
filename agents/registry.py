"""Agent registry for NEXUS OS.

Provides centralised agent lifecycle management and discovery.

* Register agents by name.
* Look up agents by name or by capability.
* Start / stop all agents in one call.
"""

from __future__ import annotations

import logging
from typing import Iterator

from agents.base import BaseAgent

logger = logging.getLogger("nexus.agent.registry")


class AgentRegistry:
    """Central store for agent instances.

    Usage::

        registry = AgentRegistry()
        registry.register(my_agent)
        registry.start_all()

        agent = registry.get("my_agent")
        matches = registry.find_by_capability("file_read")
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, agent: BaseAgent) -> None:
        """Register an agent.  Overwrites if one with the same name exists."""
        self._agents[agent.name] = agent
        logger.info("Registered agent: %s", agent.name)

    def unregister(self, name: str) -> None:
        """Remove an agent by name (no-op if not found)."""
        removed = self._agents.pop(name, None)
        if removed:
            logger.info("Unregistered agent: %s", name)

    # ── Lookup ───────────────────────────────────────────────────────────

    def get(self, name: str) -> BaseAgent | None:
        """Return the agent with *name*, or ``None``."""
        return self._agents.get(name)

    def find_by_capability(self, capability_name: str) -> list[BaseAgent]:
        """Return all agents that declare a matching capability."""
        return [
            agent
            for agent in self._agents.values()
            if any(c.name == capability_name for c in agent.capabilities)
        ]

    # ── Iteration / introspection ────────────────────────────────────────

    def list_agents(self) -> list[BaseAgent]:
        """Return all registered agents (insertion order)."""
        return list(self._agents.values())

    def describe_all(self) -> list[dict]:
        """Return metadata dicts for every agent."""
        return [a.describe() for a in self._agents.values()]

    def __len__(self) -> int:
        return len(self._agents)

    def __iter__(self) -> Iterator[BaseAgent]:
        return iter(self._agents.values())

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start_all(self) -> None:
        """Call ``on_start()`` on every registered agent."""
        for agent in self._agents.values():
            agent.on_start()
        logger.info("Started %d agent(s)", len(self._agents))

    def stop_all(self) -> None:
        """Call ``on_stop()`` on every registered agent (reverse order)."""
        for agent in reversed(list(self._agents.values())):
            agent.on_stop()
        logger.info("Stopped %d agent(s)", len(self._agents))
