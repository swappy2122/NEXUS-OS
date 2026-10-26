"""Model router for NEXUS OS.

The ``ModelRouter`` decouples agents from specific LLM backends.  Agents
call ``router.chat(messages, ...)`` and the router decides which backend
to forward to based on:

1. **Model routing strategy** — a pluggable ``ModelRoutingStrategy``
   classifies the request by task category and complexity tier, and may
   short-circuit with a bypass response for deterministic operations.
2. **Tier → backend mapping** — a ``ModelTierConfig`` maps each
   complexity tier (bypass / light / standard / heavy) to a registered
   backend name.
3. **Agent-role overrides** — explicit ``set_route(role, backend)``
   rules take precedence over strategy-based routing when configured.

For the v0.1 prototype, all agents route to a single Ollama backend.
Adding per-agent or per-task-complexity routing is a configuration
change, not a code change.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from core.types import ModelResponse
from models.base_backend import BaseModelBackend
from models.routing_strategy import (
    DefaultPassthroughStrategy,
    ModelRoutingStrategy,
)
from models.routing_types import (
    ComplexityTier,
    ModelTierConfig,
    RoutingDecision,
    TaskCategory,
)

logger = logging.getLogger("NEXUS_OS.models.router")

DEFAULT_BACKEND = "default"


class ModelRouter:
    """Routes inference requests to registered model backends.

    Usage::

        router = ModelRouter(
            strategy=RuleBasedStrategy(),
            tier_config=ModelTierConfig(light="ollama", standard="ollama", heavy="ollama"),
        )
        router.register_backend(OllamaBackend(model_id="llama3.2"))
        router.set_route("file", "ollama")    # file agent → ollama
        router.set_route("*", "ollama")       # fallback for all

        response = await router.chat(messages=[...], agent_role="file")
    """

    def __init__(
        self,
        strategy: ModelRoutingStrategy | None = None,
        tier_config: ModelTierConfig | None = None,
    ) -> None:
        self._backends: dict[str, BaseModelBackend] = {}
        self._routes: dict[str, str] = {}  # agent_role → backend name
        self._strategy = strategy or DefaultPassthroughStrategy()
        self._tier_config = tier_config or ModelTierConfig()

        # Telemetry counters
        self._stats: dict[str, int] = {
            "total_requests": 0,
            "bypassed": 0,
            "routed_light": 0,
            "routed_standard": 0,
            "routed_heavy": 0,
        }

    # -- configuration -----------------------------------------------------

    @property
    def strategy(self) -> ModelRoutingStrategy:
        """The active routing strategy."""
        return self._strategy

    def set_strategy(self, strategy: ModelRoutingStrategy) -> None:
        """Replace the routing strategy at runtime."""
        logger.info(
            "Model routing strategy changed: %s → %s",
            type(self._strategy).__name__,
            type(strategy).__name__,
        )
        self._strategy = strategy

    @property
    def tier_config(self) -> ModelTierConfig:
        """The active tier → backend mapping."""
        return self._tier_config

    def set_tier_config(self, config: ModelTierConfig) -> None:
        """Replace the tier configuration at runtime."""
        self._tier_config = config
        logger.info("Model tier config updated: %s", config)

    # -- registration ------------------------------------------------------

    def register_backend(self, backend: BaseModelBackend) -> None:
        """Register a model backend under its ``name``."""
        self._backends[backend.name] = backend
        # First registered backend becomes the default
        if DEFAULT_BACKEND not in self._backends:
            self._backends[DEFAULT_BACKEND] = backend
        logger.info(
            "Registered model backend: %s (model=%s)",
            backend.name,
            backend.model_id,
        )

    # -- routing -----------------------------------------------------------

    def set_route(self, agent_role: str, backend_name: str) -> None:
        """Map *agent_role* to a specific backend.

        Use ``"*"`` as *agent_role* to set the fallback for all
        unspecified roles.

        .. note::

           Explicit per-role routes take precedence over strategy-based
           tier routing.  Remove a route with ``del router._routes[role]``
           to fall back to strategy-based routing for that role.
        """
        self._routes[agent_role] = backend_name

    def _resolve_backend_by_name(self, name: str) -> BaseModelBackend | None:
        """Look up a backend by name, falling back to the default."""
        return self._backends.get(name) or self._backends.get(DEFAULT_BACKEND)

    def _resolve_backend(self, agent_role: str) -> BaseModelBackend:
        """Resolve which backend to use for *agent_role* using legacy routes.

        This is the pre-strategy path: agent_role → backend name lookup.
        """
        backend_name = self._routes.get(
            agent_role,
            self._routes.get("*", DEFAULT_BACKEND),
        )
        backend = self._backends.get(backend_name)
        if backend is None:
            backend = self._backends.get(DEFAULT_BACKEND)
        if backend is None:
            raise RuntimeError(
                f"No model backend configured for role '{agent_role}' "
                f"and no default backend registered."
            )
        return backend

    # -- inference ---------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        agent_role: str = "*",
        **kwargs: Any,
    ) -> ModelResponse:
        """Route a chat-completion request to the appropriate backend.

        This method satisfies the ``LLMProvider`` protocol so the
        router can be injected directly into agents via ``set_llm()``.

        Routing flow:

        1. Run the ``ModelRoutingStrategy.classify()`` to get a
           :class:`RoutingDecision`.
        2. If the decision tier is ``BYPASS`` and a ``bypass_response``
           is provided, return it immediately (no backend call).
        3. If the agent role has an explicit route override, use that
           backend (backward-compatible path).
        4. Otherwise, map the decision's tier to a backend via
           ``ModelTierConfig`` and call it.

        Parameters:
            messages: OpenAI-style message list.
            tools: Optional tool schemas for function-calling.
            agent_role: Used for routing (keyword-only, default ``"*"``).
            **kwargs: Passed through to the backend.
        """
        self._stats["total_requests"] += 1
        start = time.monotonic()

        # Step 1: Classify the request
        decision = self._strategy.classify(
            messages,
            agent_role=agent_role,
            tools=tools,
            **kwargs,
        )

        logger.debug(
            "Routing decision: category=%s tier=%s reason='%s' agent_role=%s",
            decision.category.value,
            decision.tier.value,
            decision.reason,
            agent_role,
        )

        # Step 2: Handle BYPASS — return without calling any backend
        if decision.tier == ComplexityTier.BYPASS and decision.bypass_response is not None:
            self._stats["bypassed"] += 1
            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                "BYPASS %s (%.1f ms): %s",
                agent_role,
                elapsed,
                decision.reason,
            )
            return decision.bypass_response

        # Step 3: Resolve backend
        backend = self._pick_backend(agent_role, decision)

        # Step 4: Call the backend
        self._stats[f"routed_{decision.tier.value}"] = (
            self._stats.get(f"routed_{decision.tier.value}", 0) + 1
        )

        logger.debug(
            "Routing %s → %s (%s) [tier=%s]",
            agent_role,
            backend.name,
            backend.model_id,
            decision.tier.value,
        )
        return await backend.chat(messages, tools, **kwargs)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        agent_role: str = "*",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream provider deltas using the same routing policy as ``chat``."""
        decision = self._strategy.classify(messages, agent_role=agent_role, tools=tools, **kwargs)
        if decision.tier == ComplexityTier.BYPASS and decision.bypass_response is not None:
            if decision.bypass_response.content:
                yield decision.bypass_response.content
            return
        backend = self._pick_backend(agent_role, decision)
        async for delta in backend.stream_chat(messages, tools, **kwargs):
            yield delta

    def _pick_backend(
        self,
        agent_role: str,
        decision: RoutingDecision,
    ) -> BaseModelBackend:
        """Determine the backend for a classified request.

        Priority order:
        1. ``decision.backend_override`` (strategy forced a specific backend).
        2. Explicit ``set_route()`` mapping for *agent_role*.
        3. Tier → backend via ``ModelTierConfig``.
        4. Default fallback.
        """
        # 1. Strategy-level override
        if decision.backend_override:
            backend = self._backends.get(decision.backend_override)
            if backend:
                return backend
            logger.warning(
                "Strategy requested backend '%s' but it is not registered. "
                "Falling through.",
                decision.backend_override,
            )

        # 2. Explicit per-role route
        if agent_role in self._routes:
            backend = self._backends.get(self._routes[agent_role])
            if backend:
                return backend

        # 3. Tier-based mapping
        tier_backend_name = self._tier_config.get_backend_for_tier(decision.tier)
        backend = self._backends.get(tier_backend_name)
        if backend:
            return backend

        # 4. Wildcard route → default
        return self._resolve_backend(agent_role)

    # -- introspection -----------------------------------------------------

    def list_backends(self) -> list[dict[str, str]]:
        """Return info about all registered backends."""
        return [
            {"name": b.name, "model_id": b.model_id}
            for name, b in self._backends.items()
            if name != DEFAULT_BACKEND
        ]

    async def health_check(self) -> dict[str, bool]:
        """Check availability of all backends."""
        results = {}
        for name, backend in self._backends.items():
            if name == DEFAULT_BACKEND:
                continue
            results[name] = await backend.is_available()
        return results

    def get_routing_stats(self) -> dict[str, Any]:
        """Return routing telemetry counters."""
        return {
            **self._stats,
            "strategy": type(self._strategy).__name__,
            "tier_config": {
                "bypass": self._tier_config.bypass,
                "light": self._tier_config.light,
                "standard": self._tier_config.standard,
                "heavy": self._tier_config.heavy,
            },
            "registered_backends": [
                name for name in self._backends if name != DEFAULT_BACKEND
            ],
            "explicit_routes": dict(self._routes),
        }
