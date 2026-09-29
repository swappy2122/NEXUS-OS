"""Lightweight in-process event bus for NEXUS OS.

Provides decoupled publish / subscribe communication so that components
like the audit log can react to tool executions without the tool layer
having to import the audit module directly.

For a prototype this is a simple callback registry.  It can later be
swapped for Redis Pub/Sub or NATS without changing the publish/subscribe
interface.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger("NEXUS_OS.event_bus")

# Type aliases
SyncCallback = Callable[[dict[str, Any]], None]
AsyncCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
Callback = SyncCallback | AsyncCallback


class EventBus:
    """In-memory publish/subscribe event bus.

    Usage::

        bus = EventBus()
        bus.subscribe("tool.executed", my_handler)
        await bus.publish("tool.executed", {"tool": "file_read", ...})
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)

    # -- public API --------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callback) -> None:
        """Register *callback* to be invoked whenever *event_type* is published."""
        self._subscribers[event_type].append(callback)
        logger.debug("Subscribed %s to '%s'", callback.__name__, event_type)

    def unsubscribe(self, event_type: str, callback: Callback) -> None:
        """Remove a previously registered callback."""
        try:
            self._subscribers[event_type].remove(callback)
        except ValueError:
            pass

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event, invoking all registered callbacks.

        Both sync and async callbacks are supported.  Errors in individual
        callbacks are logged but never propagate to the publisher.
        """
        for cb in self._subscribers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception:
                logger.exception(
                    "Error in event callback %s for '%s'",
                    cb.__name__,
                    event_type,
                )

    def clear(self) -> None:
        """Remove all subscriptions (useful in tests)."""
        self._subscribers.clear()
