"""Model router for NEXUS OS.

The ``ModelRouter`` decouples agents from specific LLM backends.  Agents
call ``router.chat(agent_role, messages, ...)`` and the router decides
which backend to forward to based on configurable routing rules.

For the v0.1 prototype all agents route to a single Ollama backend.
Adding per-agent or per-task-complexity routing is a configuration
change, not a code change.
"""

from __future__ import annotations

import logging
from typing import Any

from core.types import ModelResponse
from models.base_backend import BaseModelBackend

logger = logging.getLogger("NEXUS_OS.models.router")

DEFAULT_BACKEND = "default"


class ModelRouter:
    """Routes inference requests to registered model backends.

    Usage::

        router = ModelRouter()
        router.register_backend(OllamaBackend(model_id="llama3.2"))
        router.set_route("file", "ollama")    # file agent → ollama
        router.set_route("*", "ollama")       # fallback for all

        response = await router.chat("file", messages=[...])
    """

    def __init__(self) -> None:
        self._backends: dict[str, BaseModelBackend] = {}
        self._routes: dict[str, str] = {}  # agent_role → backend name

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
        """
        self._routes[agent_role] = backend_name

    def _resolve_backend(self, agent_role: str) -> BaseModelBackend:
        """Resolve which backend to use for *agent_role*."""
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

        Parameters:
            messages: OpenAI-style message list.
            tools: Optional tool schemas for function-calling.
            agent_role: Used for routing (keyword-only, default ``"*"``).
            **kwargs: Passed through to the backend.
        """
        backend = self._resolve_backend(agent_role)
        logger.debug(
            "Routing %s → %s (%s)",
            agent_role,
            backend.name,
            backend.model_id,
        )
        return await backend.chat(messages, tools, **kwargs)

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
