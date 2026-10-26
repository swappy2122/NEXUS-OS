"""WebSocket bridge between Python WindowAgent and Unity VRWindowManager.

This is a thin transport layer.  It does not contain business logic —
that belongs in ``WindowAgent`` and ``WindowRegistry``.

Responsibilities
────────────────
1. Start a WebSocket server on ``host:port`` (default ``127.0.0.1:9100``).
2. Subscribe to all ``window.command.*`` EventBus topics.
3. Serialize ``WindowCommand`` → JSON and send to any connected Unity client.
4. Receive ``WindowEvent`` JSON from Unity and publish to ``window.event.*``.
5. Handle connection lifecycle (connect, disconnect, reconnect).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from core.event_bus import EventBus
from vr.window_protocol import (
    WindowCommand,
    WindowCommandType,
    WindowEvent,
    WindowEventType,
)

logger = logging.getLogger("nexus.vr.bridge")

# All command topics we subscribe to on the EventBus
_COMMAND_TOPICS = [
    f"window.command.{cmd.value.split('.')[-1]}"
    for cmd in WindowCommandType
]


class VRBridge:
    """Async WebSocket server bridging the NEXUS OS EventBus to Unity.

    Usage::

        bridge = VRBridge(event_bus)
        await bridge.start()     # non-blocking, runs in background
        ...
        await bridge.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        host: str = "127.0.0.1",
        port: int = 9100,
    ) -> None:
        self._event_bus = event_bus
        self._host = host
        self._port = port

        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._running = False

    # ── Public API ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the WebSocket server and subscribe to EventBus topics."""
        if self._running:
            logger.warning("VRBridge already running")
            return

        # Subscribe to all command topics
        for topic in _COMMAND_TOPICS:
            self._event_bus.subscribe(topic, self._on_command)

        self._server = await asyncio.start_server(
            self._handle_client,
            self._host,
            self._port,
        )
        self._running = True
        logger.info("VRBridge listening on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Gracefully shut down all connections and the server."""
        self._running = False

        # Unsubscribe
        for topic in _COMMAND_TOPICS:
            self._event_bus.unsubscribe(topic, self._on_command)

        # Close all client connections
        for writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

        # Stop the server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("VRBridge stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ── Client Connection Handling ───────────────────────────────────────

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single Unity client connection.

        Reads newline-delimited JSON messages from Unity and publishes
        them as ``window.event.*`` on the EventBus.
        """
        addr = writer.get_extra_info("peername")
        self._clients.add(writer)
        logger.info("Unity client connected: %s", addr)

        try:
            while self._running:
                data = await reader.readline()
                if not data:
                    break   # client disconnected

                raw = data.decode("utf-8").strip()
                if raw:
                    await self._on_unity_message(raw)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error reading from Unity client %s", addr)
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("Unity client disconnected: %s", addr)

    # ── EventBus → Unity (commands) ─────────────────────────────────────

    async def _on_command(self, data: dict[str, Any]) -> None:
        """EventBus callback: serialize a WindowCommand and send to Unity."""
        try:
            # data is expected to be the model_dump() of a WindowCommand
            payload_json = json.dumps(data, default=str) + "\n"
            payload_bytes = payload_json.encode("utf-8")

            # Broadcast to all connected Unity clients
            dead_clients: list[asyncio.StreamWriter] = []
            for writer in self._clients:
                try:
                    writer.write(payload_bytes)
                    await writer.drain()
                except Exception:
                    dead_clients.append(writer)

            # Clean up disconnected clients
            for writer in dead_clients:
                self._clients.discard(writer)
                try:
                    writer.close()
                except Exception:
                    pass

            logger.debug("Sent command to %d client(s): %s",
                         len(self._clients), data.get("type", "unknown"))
        except Exception:
            logger.exception("Failed to send command to Unity")

    # ── Unity → EventBus (events) ──────────────────────────────────────

    async def _on_unity_message(self, raw: str) -> None:
        """Parse incoming Unity JSON and publish as a WindowEvent on the EventBus."""
        try:
            msg = json.loads(raw)
            event_type = msg.get("type", "")

            # Validate it's a known event type
            try:
                WindowEventType(event_type)
            except ValueError:
                logger.warning("Unknown event type from Unity: %s", event_type)
                return

            # Build a topic from the event type: "window.created" → "window.event.created"
            suffix = event_type.split(".")[-1] if "." in event_type else event_type
            topic = f"window.event.{suffix}"

            await self._event_bus.publish(topic, msg)
            logger.debug("Published Unity event: %s (window=%s)",
                         topic, msg.get("window_id", "?"))
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from Unity: %.100s", raw)
        except Exception:
            logger.exception("Error processing Unity message")

    # ── Direct Send (for testing / manual commands) ──────────────────────

    async def send_raw(self, message: str) -> int:
        """Send a raw string to all connected Unity clients.

        Returns the number of clients that received the message.
        """
        payload = (message.rstrip("\n") + "\n").encode("utf-8")
        sent = 0
        for writer in list(self._clients):
            try:
                writer.write(payload)
                await writer.drain()
                sent += 1
            except Exception:
                self._clients.discard(writer)
        return sent
