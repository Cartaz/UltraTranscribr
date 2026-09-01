"""Clipboard-safe text insertion using the keyboard-only RemoteDesktop portal."""
from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import Any

from PySide6.QtCore import QByteArray, QMimeData, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ui.native.remote_desktop import RemoteDesktopKeyboardPortal

logger = logging.getLogger(__name__)
_MARKER_MIME = "application/x-ultratranscribr-dictation-token"
_RESTORE_DELAY_MS = 220
_NO_SPACE_BEFORE = set(".,;:!?)]}»")


class SystemTextInjector(QObject):
    """Serialize clipboard transactions and never overwrite a user clipboard change."""

    insertionCompleted = Signal(str)
    errorOccurred = Signal(str)
    _enqueueSignal = Signal(int, str)

    def __init__(self, remote: RemoteDesktopKeyboardPortal, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._remote = remote
        self._queue: deque[tuple[int, str]] = deque()
        self._busy = False
        self._closed = False
        self._has_inserted = False
        self._generation = 0
        self._active_transaction: tuple[int, str, Any, bytes, QMimeData] | None = None
        self._enqueueSignal.connect(self._enqueue_on_gui)
        self._remote.readyChanged.connect(self._on_ready_changed)
        self._remote.pasteCompleted.connect(self._on_paste_completed)
        self._remote.errorOccurred.connect(self._on_remote_error)

    def begin_session(self) -> None:
        if self._closed:
            return
        self._generation += 1
        self._has_inserted = False
        self._queue.clear()
        self._remote.ensure_ready()

    def insert_delta(self, text: str) -> None:
        if self._closed:
            return
        value = str(text or "").strip()
        if not value:
            return
        if self._has_inserted and value[0] not in _NO_SPACE_BEFORE:
            value = " " + value
        self._has_inserted = True
        self._enqueueSignal.emit(self._generation, value)

    def insert_final(self, text: str) -> None:
        if self._closed:
            return
        value = str(text or "").strip()
        if value:
            self._enqueueSignal.emit(self._generation, value)

    @Slot(int, str)
    def _enqueue_on_gui(self, generation: int, text: str) -> None:
        if self._closed or generation != self._generation:
            return
        self._queue.append((generation, text))
        self._process_next()

    def _process_next(self) -> None:
        if self._closed or self._busy:
            return
        while self._queue:
            generation, text = self._queue.popleft()
            if generation == self._generation:
                break
        else:
            return
        if not self._remote.ready:
            self._queue.appendleft((generation, text))
            self._remote.ensure_ready()
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self._fail("Clipboard Qt non disponibile")
            return
        previous = self._clone_mime(clipboard.mimeData())
        marker = uuid.uuid4().hex.encode("ascii")
        temporary = QMimeData()
        temporary.setText(text)
        temporary.setData(_MARKER_MIME, QByteArray(marker))
        clipboard.setMimeData(temporary)
        self._busy = True
        self._active_transaction = (generation, text, clipboard, marker, previous)
        if not self._remote.paste_shortcut():
            self._restore_active_transaction()
            self._busy = False
            self._fail("RemoteDesktop non è pronto per l'inserimento")

    @Slot()
    def _on_paste_completed(self) -> None:
        transaction = self._active_transaction
        if transaction is None:
            return
        generation, text, clipboard, marker, previous = transaction

        def restore() -> None:
            if self._active_transaction is not transaction:
                return
            self._restore_if_owned(clipboard, marker, previous)
            self._active_transaction = None
            self._busy = False
            if self._closed:
                return
            if generation == self._generation:
                self.insertionCompleted.emit(text)
            self._process_next()

        QTimer.singleShot(_RESTORE_DELAY_MS, restore)

    @Slot(bool)
    def _on_ready_changed(self, ready: bool) -> None:
        if ready and not self._closed:
            self._process_next()

    @Slot(str)
    def _on_remote_error(self, message: str) -> None:
        if self._closed:
            return
        self._restore_active_transaction()
        self._queue.clear()
        self._busy = False
        self.errorOccurred.emit(message)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._restore_active_transaction()
        self._queue.clear()
        self._busy = False

    def _restore_active_transaction(self) -> None:
        transaction = self._active_transaction
        self._active_transaction = None
        if transaction is None:
            return
        _generation, _text, clipboard, marker, previous = transaction
        self._restore_if_owned(clipboard, marker, previous)

    @staticmethod
    def _clone_mime(source: QMimeData | None) -> QMimeData:
        clone = QMimeData()
        if source is None:
            return clone
        for fmt in source.formats():
            clone.setData(fmt, source.data(fmt))
        return clone

    @staticmethod
    def _restore_if_owned(clipboard, marker: bytes, previous: QMimeData) -> None:
        current = clipboard.mimeData()
        current_marker = (
            bytes(current.data(_MARKER_MIME))
            if current and current.hasFormat(_MARKER_MIME)
            else b""
        )
        if current_marker == marker:
            clipboard.setMimeData(previous)

    def _fail(self, message: str) -> None:
        logger.error("Inserimento dettatura: %s", message)
        self._queue.clear()
        self._busy = False
        if not self._closed:
            self.errorOccurred.emit(message)
