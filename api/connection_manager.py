"""Authenticated in-process WebSocket connection management for NEXUS OS."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from core.event_bus import EventBus
from security.sessions import AuthenticatedSession

logger = logging.getLogger("nexus.api.websocket")


@dataclass
class ClientConnection:
    """Live connection metadata; bearer credentials are never retained."""

    connection_id: str
    session: AuthenticatedSession
    websocket: WebSocket
    last_activity: float


class ConnectionManager:
    """Manage authenticated WebSockets in one process."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        stale_timeout_seconds: float = 90.0,
        clock: Any = time.monotonic,
    ) -> None:
        if stale_timeout_seconds <= 0:
            raise ValueError("stale_timeout_seconds must be positive")
        self._event_bus = event_bus
        self._stale_timeout = stale_timeout_seconds
        self._clock = clock
        self._connections: dict[str, ClientConnection] = {}
        self._lock = asyncio.Lock()
        self._subscribed = False
        self._cleanup_task: asyncio.Task[None] | None = None

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def subscribed(self) -> bool:
        return self._subscribed

    async def start(self) -> None:
        """Subscribe to supported backend events and start stale cleanup."""
        if not self._subscribed:
            for event_type in self._event_types:
                self._event_bus.subscribe(event_type, self._on_event)
            self._subscribed = True
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Close connections and remove EventBus subscriptions."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        if self._subscribed:
            for event_type in self._event_types:
                self._event_bus.unsubscribe(event_type, self._on_event)
            self._subscribed = False

        async with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        await asyncio.gather(
            *(self._close_socket(connection.websocket) for connection in connections),
            return_exceptions=True,
        )

    async def register(
        self,
        websocket: WebSocket,
        session: AuthenticatedSession,
    ) -> str:
        """Register a socket after its handshake has been authenticated."""
        connection = ClientConnection(
            connection_id=f"conn_{uuid4().hex}",
            session=session,
            websocket=websocket,
            last_activity=self._clock(),
        )
        async with self._lock:
            self._connections[connection.connection_id] = connection
        return connection.connection_id

    async def remove(self, connection_id: str) -> bool:
        async with self._lock:
            return self._connections.pop(connection_id, None) is not None

    async def get(self, connection_id: str) -> ClientConnection | None:
        async with self._lock:
            return self._connections.get(connection_id)

    async def touch(self, connection_id: str) -> None:
        async with self._lock:
            connection = self._connections.get(connection_id)
            if connection is not None:
                connection.last_activity = self._clock()

    async def send_to(self, connection_id: str, message: str) -> bool:
        connection = await self.get(connection_id)
        return connection is not None and await self._send(connection, message)

    async def broadcast(self, message: str, *, session_id: str | None = None) -> int:
        async with self._lock:
            connections = [
                connection
                for connection in self._connections.values()
                if session_id is None or connection.session.session_id == session_id
            ]
        results = await asyncio.gather(
            *(self._send(connection, message) for connection in connections),
            return_exceptions=True,
        )
        return sum(result is True for result in results)

    async def cleanup_stale(self) -> int:
        cutoff = self._clock() - self._stale_timeout
        async with self._lock:
            stale = [
                connection
                for connection in self._connections.values()
                if connection.last_activity < cutoff
            ]
            for connection in stale:
                self._connections.pop(connection.connection_id, None)
        await asyncio.gather(
            *(self._close_socket(connection.websocket) for connection in stale),
            return_exceptions=True,
        )
        return len(stale)

    async def _send(self, connection: ClientConnection, message: str) -> bool:
        try:
            await connection.websocket.send_text(message)
            return True
        except Exception:
            logger.debug("WebSocket send failed for connection %s", connection.connection_id)
            await self.remove(connection.connection_id)
            return False

    async def _on_event(self, data: dict[str, Any]) -> None:
        """Forward legacy window commands as typed protocol envelopes."""
        from vr.window_protocol import WindowCommand, build_nexus_message

        try:
            command = WindowCommand.model_validate(data)
            payload = dict(command.payload)
            if "window_id" not in payload:
                payload["window_id"] = command.window_id
            message = build_nexus_message(
                command.type.value,
                payload,
                correlation_id=command.request_id,
            )
            await self.broadcast(message.to_json())
        except Exception:
            logger.warning("Rejected unsupported EventBus WebSocket payload")

    async def _cleanup_loop(self) -> None:
        interval = min(self._stale_timeout / 2, 30.0)
        try:
            while True:
                await asyncio.sleep(interval)
                await self.cleanup_stale()
        except asyncio.CancelledError:
            raise

    @staticmethod
    async def _close_socket(websocket: WebSocket) -> None:
        try:
            result = websocket.close(code=1001)
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    @property
    def _event_types(self) -> tuple[str, ...]:
        return tuple(
            f"window.command.{suffix}"
            for suffix in (
                "create", "close", "move", "resize", "rotate", "focus",
                "set_state", "set_anchor", "set_title", "batch",
            )
        )