# core/event_bus.py
"""Synchronous process-wide event bus used by legacy cross-module integrations.

The bus is thread-safe for subscription bookkeeping, but event handlers execute
synchronously in the emitter's thread. New focused services should prefer
explicit callbacks/event sinks where practical instead of expanding this global
singleton dependency.

Event names follow the ``module_action_state`` convention where applicable
(e.g. ``process_started`` and ``config_changed``).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe registry with synchronous handler dispatch.

    ``subscribe``/``unsubscribe`` are protected by an internal lock. ``emit``
    snapshots the current handlers under that lock and then invokes them in the
    emitter's thread. Consequently, a slow handler blocks its emitter; callers
    must move expensive work off latency-sensitive threads themselves.
    """

    _instance: EventBus | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> EventBus:
        """Return the process-wide EventBus singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._handlers: dict[str, list[Callable]] = defaultdict(list)
                cls._instance._bus_lock = threading.Lock()
            return cls._instance

    @staticmethod
    def _handler_name(handler: Callable) -> str:
        """Return a readable name for functions and callable objects."""
        return getattr(handler, "__name__", handler.__class__.__name__)

    def subscribe(self, event: str, handler: Callable) -> None:
        """Register ``handler`` for ``event``."""
        with self._bus_lock:
            self._handlers[event].append(handler)
        logger.debug(
            "Handler %s iscritto a '%s'",
            self._handler_name(handler),
            event,
        )

    def unsubscribe(self, event: str, handler: Callable) -> None:
        """Remove ``handler`` from ``event`` when currently registered."""
        with self._bus_lock:
            handlers = self._handlers.get(event, [])
            if handler in handlers:
                handlers.remove(handler)
        logger.debug(
            "Handler %s rimosso da '%s'",
            self._handler_name(handler),
            event,
        )

    def emit(self, event: str, data: Any = None) -> None:
        """Invoke a snapshot of ``event`` handlers in the emitter's thread.

        A failing handler is logged with its traceback and does not prevent
        subsequent handlers from running.
        """
        with self._bus_lock:
            handlers = list(self._handlers.get(event, []))

        for handler in handlers:
            try:
                handler(data)
            except Exception:
                logger.exception(
                    "Errore nell'handler %s per l'evento '%s'",
                    self._handler_name(handler),
                    event,
                )

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton for isolated tests only."""
        with cls._lock:
            cls._instance = None
