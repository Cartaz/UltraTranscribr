# core/event_bus.py
"""Event bus singleton per la comunicazione asincrona tra moduli.

Funge da canale di comunicazione disaccoppiato tra tutti i livelli
dell'applicazione. I nomi degli eventi seguono il pattern
modulo_azione_stato (es. process_started, config_changed).

Classes:
    EventBus: Event bus singleton thread-safe.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Event bus singleton per la comunicazione disaccoppiata tra moduli.

    Supporta registrazione (subscribe), emissione (emit) e
    deregistrazione (unsubscribe) di handler per tipo di evento.
    Thread-safe tramite lock interno.

    L'event bus non blocca mai il thread principale: gli handler
    vengono eseguiti sincronamente nel thread dell'emittente.
    """

    _instance: EventBus | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> EventBus:
        """Restituisce l'istanza singleton dell'EventBus.

        Returns:
            L'istanza singleton di EventBus.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._handlers: dict[str, list[Callable]] = defaultdict(list)
                cls._instance._bus_lock = threading.Lock()
            return cls._instance

    @staticmethod
    def _handler_name(handler: Callable) -> str:
        """Restituisce un nome leggibile anche per callable senza __name__."""
        return getattr(handler, "__name__", handler.__class__.__name__)

    def subscribe(self, event: str, handler: Callable) -> None:
        """Registra un handler per un tipo di evento.

        Args:
            event: Nome dell'evento (es. 'process_started').
            handler: Funzione callback da invocare quando l'evento viene emesso.
        """
        with self._bus_lock:
            self._handlers[event].append(handler)
        logger.debug(
            "Handler %s iscritto a '%s'",
            self._handler_name(handler),
            event,
        )

    def unsubscribe(self, event: str, handler: Callable) -> None:
        """Deregistra un handler per un tipo di evento.

        Args:
            event: Nome dell'evento.
            handler: Funzione callback da rimuovere.
        """
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
        """Emette un evento, invocando tutti gli handler registrati.

        Gli handler vengono eseguiti sincronamente nel thread dell'emittente.
        Gli errori in un handler non bloccano gli handler successivi.

        Args:
            event: Nome dell'evento (es. 'process_started').
            data: Payload dell'evento (opzionale).
        """
        with self._bus_lock:
            handlers = list(self._handlers.get(event, []))

        for handler in handlers:
            try:
                handler(data)
            except Exception as exc:
                logger.error(
                    "Errore nell'handler %s per l'evento '%s': %s",
                    self._handler_name(handler),
                    event,
                    exc,
                )

    @classmethod
    def reset(cls) -> None:
        """Resetta il singleton (solo per testing)."""
        with cls._lock:
            cls._instance = None
