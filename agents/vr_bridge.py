"""VR Bridge client for NEXUS OS.

Provides the ``IVRBridge`` protocol and a concrete ``VRBridgeClient``
implementation that communicates with the Unity VR shell over a
WebSocket connection.

Messages are serialized as JSON using the Pydantic models from
``core.vr_types``.  The bridge is bidirectional:

    Python → Unity:  ``WindowCommand``  (via ``send_command``)
    Unity → Python:  ``WindowEvent``    (via registered event handlers)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from core.vr_types import WindowCommand, WindowEvent

logger = logging.getLogger("nexus.vr_bridge")

# Type alias for event handler callbacks
EventHandler = Callable[[WindowEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

@runtime_checkable
class IVRBridge(Protocol):
    """Protocol for Python ↔ Unity VR shell communication.

    Implementations must support sending commands, registering event
    handlers, and managing the connection lifecycle.
    """

    async def send_command(self, command: WindowCommand) -> None: ...
    def on_event(self, handler: EventHandler) -> None: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

class VRBridgeClient:
    """WebSocket client that bridges Python window commands to Unity.

    Usage::

        bridge = VRBridgeClient(host="127.0.0.1", port=8769)
        bridge.on_event(my_event_handler)
        await bridge.connect()
        await bridge.send_command(some_command)
        await bridge.disconnect()

    The client automatically reconnects on disconnect with configurable
    retry behaviour.
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8769
    RECONNECT_DELAY_SECONDS = 2.0
    MAX_RECONNECT_ATTEMPTS = 10

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        auto_reconnect: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._auto_reconnect = auto_reconnect

        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._connected = False
        self._event_handlers: list[EventHandler] = []
        self._listen_task: asyncio.Task[None] | None = None
        self._command_queue: asyncio.Queue[WindowCommand] = asyncio.Queue()

    # ── connection lifecycle ─────────────────────────────────────────────

    async def connect(self) -> None:
        """Open a WebSocket-style TCP connection to the Unity bridge server.

        Starts the background listener for incoming ``WindowEvent`` messages.
        """
        if self._connected:
            logger.warning("Bridge already connected")
            return

        try:
            self._reader, self._writer = await asyncio.open_connection(
                self._host, self._port,
            )
            self._connected = True
            logger.info(
                "VR Bridge connected to %s:%d", self._host, self._port,
            )
            # Start background listener
            self._listen_task = asyncio.create_task(
                self._listen_loop(), name="vr_bridge_listener",
            )
        except (ConnectionRefusedError, OSError) as exc:
            self._connected = False
            logger.error(
                "Failed to connect to VR Bridge at %s:%d — %s",
                self._host, self._port, exc,
            )

    async def disconnect(self) -> None:
        """Cleanly close the connection and stop the listener."""
        self._connected = False

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        logger.info("VR Bridge disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── sending commands ─────────────────────────────────────────────────

    async def send_command(self, command: WindowCommand) -> None:
        """Serialize and send a ``WindowCommand`` to Unity.

        If the bridge is not connected, the command is queued and will
        be sent on reconnection.
        """
        if not self._connected or self._writer is None:
            logger.warning(
                "Bridge not connected — queueing command %s for window '%s'",
                command.command_type.value, command.window_id,
            )
            await self._command_queue.put(command)
            return

        try:
            payload = command.model_dump_json()
            # Length-prefixed framing: 4-byte big-endian length + JSON body
            data = len(payload).to_bytes(4, "big") + payload.encode("utf-8")
            self._writer.write(data)
            await self._writer.drain()
            logger.debug(
                "Sent command %s (id=%s, window=%s)",
                command.command_type.value,
                command.command_id,
                command.window_id,
            )
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            logger.error("Send failed — %s", exc)
            self._connected = False
            await self._command_queue.put(command)
            if self._auto_reconnect:
                asyncio.create_task(self._reconnect_loop())

    # ── event handling ───────────────────────────────────────────────────

    def on_event(self, handler: EventHandler) -> None:
        """Register a callback to be invoked for every incoming ``WindowEvent``."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: EventHandler) -> None:
        """Unregister a previously registered event handler."""
        try:
            self._event_handlers.remove(handler)
        except ValueError:
            pass

    # ── internal ─────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Background task that reads incoming events from Unity."""
        assert self._reader is not None
        try:
            while self._connected:
                # Read 4-byte length prefix
                length_bytes = await self._reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # Read the JSON body
                body_bytes = await self._reader.readexactly(length)
                body = body_bytes.decode("utf-8")

                try:
                    event = WindowEvent.model_validate_json(body)
                except Exception as exc:
                    logger.warning("Failed to parse WindowEvent: %s", exc)
                    continue

                logger.debug(
                    "Received event %s (window=%s)",
                    event.event_type.value,
                    event.window_id,
                )

                # Dispatch to all handlers
                for handler in self._event_handlers:
                    try:
                        await handler(event)
                    except Exception:
                        logger.exception(
                            "Error in event handler %s", handler.__name__,
                        )

        except asyncio.IncompleteReadError:
            logger.warning("Unity bridge closed the connection")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in bridge listener")
        finally:
            self._connected = False
            if self._auto_reconnect:
                asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            delay = self.RECONNECT_DELAY_SECONDS * min(attempt, 5)
            logger.info(
                "Reconnect attempt %d/%d in %.1fs…",
                attempt, self.MAX_RECONNECT_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)

            await self.connect()
            if self._connected:
                # Drain queued commands
                await self._flush_command_queue()
                return

        logger.error(
            "Failed to reconnect after %d attempts", self.MAX_RECONNECT_ATTEMPTS,
        )

    async def _flush_command_queue(self) -> None:
        """Send all queued commands that accumulated while disconnected."""
        flushed = 0
        while not self._command_queue.empty():
            command = await self._command_queue.get()
            await self.send_command(command)
            flushed += 1
        if flushed:
            logger.info("Flushed %d queued commands after reconnect", flushed)

    # ── introspection ────────────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        """Return connection status for diagnostics."""
        return {
            "host": self._host,
            "port": self._port,
            "connected": self._connected,
            "event_handlers": len(self._event_handlers),
            "queued_commands": self._command_queue.qsize(),
            "auto_reconnect": self._auto_reconnect,
        }
