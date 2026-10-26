"""Abstract model backend for NEXUS OS.

Every LLM backend (Ollama, OpenAI, Anthropic, etc.) subclasses
``BaseModelBackend`` and implements the ``chat()`` method.  This
keeps agent code completely decoupled from any specific model
provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from core.types import ModelResponse


class BaseModelBackend(ABC):
    """Abstract base class for an LLM inference backend.

    Attributes:
        name: Human-readable backend identifier (e.g. ``"ollama"``).
        model_id: The specific model to use (e.g. ``"llama3.2"``).
    """

    def __init__(self, name: str, model_id: str) -> None:
        self.name = name
        self.model_id = model_id

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send a chat-completion request and return a ``ModelResponse``.

        Parameters:
            messages: OpenAI-style message list
                (``[{"role": "user", "content": "..."}]``).
            tools: Optional list of tool schemas for function-calling.
            **kwargs: Backend-specific options (temperature, max_tokens, …).
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Return ``True`` if the backend is reachable and ready."""
        ...

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield provider text deltas when the backend supports streaming."""
        raise NotImplementedError(f"Backend '{self.name}' does not support streaming")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} model={self.model_id!r}>"
