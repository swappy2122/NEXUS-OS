"""Ollama local-inference backend for NEXUS OS.

Communicates with a locally-running Ollama server via its HTTP API.
This is the default backend for the prototype — no API keys required,
everything runs on the user's machine.

Ollama API docs: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.types import ModelResponse
from models.base_backend import BaseModelBackend

logger = logging.getLogger("NEXUS_OS.models.ollama")

# Default connection parameters
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0  # seconds — some models are slow on first load


class OllamaBackend(BaseModelBackend):
    """Ollama local LLM backend.

    Parameters:
        model_id: Ollama model tag (e.g. ``"llama3.2"``, ``"qwen2.5"``).
        base_url: Ollama server URL.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        model_id: str = "llama3.2",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(name="ollama", model_id=model_id)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send a chat request to Ollama's ``/api/chat`` endpoint."""
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        # Forward optional generation parameters
        options: dict[str, Any] = {}
        if "temperature" in kwargs:
            options["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            options["num_predict"] = kwargs["max_tokens"]
        if options:
            payload["options"] = options

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        content = message.get("content", "")

        # Parse tool calls if present
        tool_calls: list[dict[str, Any]] = []
        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            tool_calls.append({
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", {}),
            })

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model", self.model_id),
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    async def is_available(self) -> bool:
        """Ping Ollama to check if it is running."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
