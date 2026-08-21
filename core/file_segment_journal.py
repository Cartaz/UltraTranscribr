"""Persist timestamp segments emitted by the active File worker."""
from __future__ import annotations

import logging
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class FileSegmentJournal:
    """Bind FileTranscriber segment events to AppController's active history id."""

    def __init__(self, controller) -> None:
        self._controller = controller
        self._bus = EventBus()
        self._handler = self._on_segments
        self._controller.subscribe("file_transcriber_segments", self._handler)

    def close(self) -> None:
        self._bus.unsubscribe("file_transcriber_segments", self._handler)

    def _on_segments(self, payload: Any) -> None:
        if not isinstance(payload, list) or not payload:
            return
        with self._controller._lock:
            session_id = self._controller._file_history_id
        if session_id is None:
            return
        try:
            self._controller.history.append_segments(session_id, payload)
        except Exception as exc:
            logger.exception("Autosave segmenti temporizzati fallito")
            self._bus.emit("history_error", str(exc))
