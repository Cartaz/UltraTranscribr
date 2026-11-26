"""Clipboard-safe text insertion using the keyboard-only RemoteDesktop portal."""
from __future__ import annotations

import logging
import os
import uuid
from collections import deque
from typing import Any, Protocol

from PySide6.QtCore import QByteArray, QMimeData, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ui.native.remote_desktop import RemoteDesktopKeyboardPortal

logger = logging.getLogger(__name__)
_MARKER_MIME = "application/x-ultratranscribr-dictation-token"
_RESTORE_DELAY_MS = 220
# Let the user's physical modifiers (Meta of Meta+H) be released before the
# synthetic Shift+Insert, or the target sees Meta+Shift+Insert and no paste.
_RELEASE_SETTLE_MS = 150
_PASTE_TIMEOUT_MS = 5000
# Klipper's new selection reaches the compositor asynchronously.
_CLIPBOARD_SETTLE_MS = 80
# Safety net if the portal never reports the shortcut release.
_MAX_HOLD_MS = 5 * 60 * 1000
_KLIPPER_TIMEOUT_MS = 500
_NO_SPACE_BEFORE = set(".,;:!?)]}»")


class ClipboardSwap(Protocol):
    def swap_in(self, text: str) -> Any | None: ...

    def restore(self, token: Any) -> None: ...


class QtClipboardSwap:
    """Own-process clipboard: works on X11, not for an unfocused Wayland client."""

    def swap_in(self, text: str) -> Any | None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return None
        previous = self._clone_mime(clipboard.mimeData())
        marker = uuid.uuid4().hex.encode("ascii")
        temporary = QMimeData()
        temporary.setText(text)
        temporary.setData(_MARKER_MIME, QByteArray(marker))
        clipboard.setMimeData(temporary)
        return clipboard, marker, previous

    def restore(self, token: Any) -> None:
        clipboard, marker, previous = token
        current = clipboard.mimeData()
        current_marker = (
            bytes(current.data(_MARKER_MIME))
            if current and current.hasFormat(_MARKER_MIME)
            else b""
        )
        if current_marker == marker:
            clipboard.setMimeData(previous)

    @staticmethod
    def _clone_mime(source: QMimeData | None) -> QMimeData:
        clone = QMimeData()
        if source is None:
            return clone
        for fmt in source.formats():
            clone.setData(fmt, source.data(fmt))
        return clone


class KlipperClipboardSwap:
    """Put dictated text on the clipboard through Klipper on KDE Wayland.

    KWin ignores clipboard changes from a client without keyboard focus, and
    Dictation pastes into another application, so Qt's own clipboard never
    reached the target: the paste inserted the old clipboard or nothing.
    Klipper owns the clipboard through the data-control protocol instead.

    The previous clipboard is not restored: Klipper exposes only the text of
    its history top, which is wrong for images and for entries it does not
    record (password managers), and a late paste must never insert it. The
    previous entry stays one step back in Klipper's history.
    """

    SERVICE = "org.kde.klipper"

    def __init__(self) -> None:
        from PySide6.QtDBus import QDBusConnection

        self._bus = QDBusConnection.sessionBus()

    @property
    def available(self) -> bool:
        interface = self._bus.interface()
        return bool(interface and interface.isServiceRegistered(self.SERVICE).value())

    def swap_in(self, text: str) -> Any | None:
        from PySide6.QtDBus import QDBus, QDBusMessage

        message = QDBusMessage.createMethodCall(
            self.SERVICE, "/klipper", "org.kde.klipper.klipper", "setClipboardContents"
        )
        message.setArguments([text])
        reply = self._bus.call(message, QDBus.CallMode.Block, _KLIPPER_TIMEOUT_MS)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            logger.error("Klipper: %s", reply.errorMessage())
            return None
        return text

    def restore(self, token: Any) -> None:
        return None


def default_clipboard_swap() -> ClipboardSwap:
    wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    if wayland:
        logger.info("Dettatura: appunti tramite Klipper (Wayland)")
        try:
            klipper = KlipperClipboardSwap()
        except Exception:
            logger.exception("Klipper non raggiungibile")
        else:
            if klipper.available:
                return klipper
            logger.warning("Klipper assente: su Wayland la dettatura può incollare testo vecchio")
    return QtClipboardSwap()


class SystemTextInjector(QObject):
    """Serialize clipboard transactions and never overwrite a user clipboard change."""

    insertionCompleted = Signal(str)
    errorOccurred = Signal(str)
    _enqueueSignal = Signal(int, str)

    def __init__(
        self,
        remote: RemoteDesktopKeyboardPortal,
        parent: QObject | None = None,
        *,
        clipboard: ClipboardSwap | None = None,
    ) -> None:
        super().__init__(parent)
        self._remote = remote
        self._clipboard = clipboard or default_clipboard_swap()
        self._queue: deque[tuple[int, str]] = deque()
        self._busy = False
        self._closed = False
        self._held = False
        self._has_inserted = False
        self._generation = 0
        self._paste_sequence = 0
        self._hold_sequence = 0
        self._deferred_paste = None
        self._unconfirmed = None
        self._active_transaction: tuple[int, str, Any] | None = None
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
        if self._active_transaction is not None and self._active_transaction is self._unconfirmed:
            # A paste the portal never confirmed must not block every later
            # session. Anything still queued belonged to the old session.
            self._restore_active_transaction()
            self._busy = False
            self._remote.cancel_paste()
        self._remote.ensure_ready()

    def set_shortcut_held(self, held: bool) -> None:
        """Hold insertions while the user's shortcut keys are down.

        The hold ends only after the modifiers settle, so text arriving right
        after the release cannot be pasted while Meta is still applied.
        """
        logger.info("Dettatura: scorciatoia %s", "premuta" if held else "rilasciata")
        self._hold_sequence += 1
        sequence = self._hold_sequence
        if held:
            self._held = True
            QTimer.singleShot(_MAX_HOLD_MS, lambda: self._end_hold(sequence))
        elif not self._closed:
            QTimer.singleShot(_RELEASE_SETTLE_MS, lambda: self._end_hold(sequence))

    def _end_hold(self, sequence: int) -> None:
        if sequence != self._hold_sequence:
            return
        self._held = False
        deferred, self._deferred_paste = self._deferred_paste, None
        if deferred is not None:
            self._send_paste(deferred)
        else:
            self._process_next()

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

    @Slot()
    def _process_next(self) -> None:
        if self._closed or self._busy or self._held:
            return
        while self._queue:
            generation, text = self._queue.popleft()
            if generation == self._generation:
                break
        else:
            return
        if not self._remote.ready:
            logger.info("Dettatura: in attesa del permesso tastiera RemoteDesktop")
            self._queue.appendleft((generation, text))
            self._remote.ensure_ready()
            return
        token = self._clipboard.swap_in(text)
        if token is None:
            # Drop only this fragment; the rest of the session can still go.
            logger.error("Inserimento dettatura: impossibile scrivere negli appunti")
            self.errorOccurred.emit("Impossibile scrivere negli appunti")
            self._process_next()
            return
        self._busy = True
        transaction = (generation, text, token)
        self._active_transaction = transaction
        QTimer.singleShot(_CLIPBOARD_SETTLE_MS, lambda: self._send_paste(transaction))

    def _send_paste(self, transaction) -> None:
        if self._closed or self._active_transaction is not transaction:
            return
        if self._held:
            self._deferred_paste = transaction  # sent when the hold ends
            return
        if not self._remote.paste_shortcut():
            self._restore_active_transaction()
            self._busy = False
            self._fail("RemoteDesktop non è pronto per l'inserimento")
            return
        logger.info("Dettatura: incollo %d caratteri", len(transaction[1]))
        self._paste_sequence += 1
        sequence = self._paste_sequence
        QTimer.singleShot(_PASTE_TIMEOUT_MS, lambda: self._paste_timed_out(sequence, transaction))

    def _paste_timed_out(self, sequence: int, transaction) -> None:
        # Report a paste the portal has not confirmed, but keep waiting for
        # it: sending the next fragment while the old key sequence may still
        # land would paste that fragment twice. A new session starts clean.
        if self._closed or sequence != self._paste_sequence or self._active_transaction is not transaction:
            return
        self._unconfirmed = transaction
        logger.error("Inserimento dettatura: incolla non confermato da RemoteDesktop")
        self.errorOccurred.emit("Incolla non confermato da RemoteDesktop")

    @Slot()
    def _on_paste_completed(self) -> None:
        transaction = self._active_transaction
        if transaction is None:
            return
        self._paste_sequence += 1  # confirmed: the timeout no longer applies
        generation, text, token = transaction

        def restore() -> None:
            if self._active_transaction is not transaction:
                return
            self._clipboard.restore(token)
            self._active_transaction = None
            self._busy = False
            if self._closed:
                return
            logger.info("Dettatura: incolla confermato")
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
        self._clipboard.restore(transaction[2])

    def _fail(self, message: str) -> None:
        logger.error("Inserimento dettatura: %s", message)
        self._queue.clear()
        self._busy = False
        if not self._closed:
            self.errorOccurred.emit(message)
