# ui/event_bridge.py
"""Ponte tra l'EventBus e i Signal Qt per la comunicazione cross-thread.

Converte gli eventi asincroni dell'EventBus (emessi dai thread worker)
in Signal Qt thread-safe, che vengono eseguiti sul thread principale
della GUI tramite QueuedConnection automatica.

Gestisce sia gli eventi della trascrizione live che quelli della
trascrizione file, con segnali separati per ciascuna modalita.

Classes:
    EventBridge: Ponte EventBus → Signal Qt.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class EventBridge(QObject):
    """Ponte tra l'EventBus (thread worker) e i Signal Qt (thread GUI).

    Quando i thread worker emettono eventi tramite l'EventBus, questo
    bridge li converte in Signal Qt che vengono automaticamente
    inoltrati al thread principale tramite coda di eventi.

    I segnali sono separati per modalita live e file, in modo che
    ciascuna scheda possa collegarsi solo ai propri eventi.

    Signals:
        ── Live ─────────────────────────────────────────────────────
        live_new_text: Nuovo testo dalla trascrizione live.
        live_status_changed: Cambio stato trascrizione live.
        live_buffer_level: Livello buffer trascrizione live.
        live_error: Errore trascrizione live.
        process_started: Trascrizione live avviata.
        process_stopped: Trascrizione live fermata.
        drain_completed: Svuotamento buffer completato dopo stop_listening.

        ── File ─────────────────────────────────────────────────────
        file_new_text: Nuovo segmento dalla trascrizione file.
        file_status_changed: Cambio stato trascrizione file.
        file_progress: Progresso trascrizione file (0-100).
        file_error: Errore trascrizione file.
        file_completed: Trascrizione file completata.
        file_full_text: Testo completo della trascrizione file.
    """

    # ── Segnali Live ──────────────────────────────────────────────
    live_new_text = Signal(str)
    live_status_changed = Signal(str)
    live_buffer_level = Signal(int)
    live_error = Signal(str)
    process_started = Signal()
    process_stopped = Signal()
    drain_completed = Signal()

    # ── Segnali File ──────────────────────────────────────────────
    file_new_text = Signal(str)
    file_status_changed = Signal(str)
    file_progress = Signal(int)
    file_error = Signal(str)
    file_completed = Signal()
    file_full_text = Signal(str)

    def __init__(self) -> None:
        """Inizializza il bridge e iscrive gli handler all'EventBus."""
        super().__init__()
        self._bus = EventBus()
        self._subscribe_live()
        self._subscribe_file()

    # ── Sottoscrizioni Live ────────────────────────────────────────

    def _subscribe_live(self) -> None:
        """Iscrive gli handler per gli eventi della trascrizione live."""
        self._bus.subscribe("transcriber_new_text", self._on_live_text)
        self._bus.subscribe(
            "transcriber_status_changed", self._on_live_status)
        self._bus.subscribe(
            "transcriber_buffer_level", self._on_live_buffer)
        self._bus.subscribe("transcriber_error", self._on_live_error)
        self._bus.subscribe(
            "process_started", lambda _: self.process_started.emit())
        self._bus.subscribe(
            "process_stopped", lambda _: self.process_stopped.emit())
        self._bus.subscribe(
            "transcriber_drained", lambda _: self.drain_completed.emit())

    def _on_live_text(self, data: object) -> None:
        """Converte l'evento transcriber_new_text in Signal Qt."""
        if isinstance(data, str):
            self.live_new_text.emit(data)

    def _on_live_status(self, data: object) -> None:
        """Converte l'evento transcriber_status_changed in Signal Qt."""
        if isinstance(data, str):
            self.live_status_changed.emit(data)

    def _on_live_buffer(self, data: object) -> None:
        """Converte l'evento transcriber_buffer_level in Signal Qt."""
        if isinstance(data, int):
            self.live_buffer_level.emit(data)

    def _on_live_error(self, data: object) -> None:
        """Converte l'evento transcriber_error in Signal Qt."""
        if isinstance(data, str):
            self.live_error.emit(data)

    # ── Sottoscrizioni File ────────────────────────────────────────

    def _subscribe_file(self) -> None:
        """Iscrive gli handler per gli eventi della trascrizione file."""
        self._bus.subscribe(
            "file_transcriber_new_text", self._on_file_text)
        self._bus.subscribe(
            "file_transcriber_status_changed", self._on_file_status)
        self._bus.subscribe(
            "file_transcriber_progress", self._on_file_progress)
        self._bus.subscribe(
            "file_transcriber_error", self._on_file_error)
        self._bus.subscribe(
            "file_transcriber_completed", lambda _: self.file_completed.emit())
        self._bus.subscribe(
            "file_transcriber_full_text", self._on_file_full_text)

    def _on_file_text(self, data: object) -> None:
        """Converte l'evento file_transcriber_new_text in Signal Qt."""
        if isinstance(data, str):
            self.file_new_text.emit(data)

    def _on_file_status(self, data: object) -> None:
        """Converte l'evento file_transcriber_status_changed in Signal Qt."""
        if isinstance(data, str):
            self.file_status_changed.emit(data)

    def _on_file_progress(self, data: object) -> None:
        """Converte l'evento file_transcriber_progress in Signal Qt."""
        if isinstance(data, int):
            self.file_progress.emit(data)

    def _on_file_error(self, data: object) -> None:
        """Converte l'evento file_transcriber_error in Signal Qt."""
        if isinstance(data, str):
            self.file_error.emit(data)

    def _on_file_full_text(self, data: object) -> None:
        """Converte l'evento file_transcriber_full_text in Signal Qt."""
        if isinstance(data, str):
            self.file_full_text.emit(data)
