"""Queued worker results, feedback, clipboard and native dialogs."""

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

logger = logging.getLogger(__name__)
MEDIA_FILTER = "Media (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.opus *.mp4 *.mkv *.webm *.mov *.avi);;Tutti i file (*)"


class Feedback(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._message = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    @Property(str, notify=changed)
    def message(self):
        return self._message

    @Slot(str)
    def show(self, message):
        self._message = str(message)
        self.changed.emit()
        self._timer.start(8000)

    @Slot()
    def dismiss(self):
        self._message = ""
        self.changed.emit()

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.show("Testo copiato")


class Adapter(QObject):
    completed = Signal(object)

    def __init__(self, application, feedback, parent=None):
        super().__init__(parent)
        self.application = application
        self.feedback = feedback
        self._closed = False
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _complete(self, callback):
        if not self._closed:
            self.attempt(callback)

    def attempt(self, operation):
        try:
            return operation()
        except Exception as exc:
            logger.exception("Operazione UI fallita")
            self.feedback.show(exc)
            return None

    def background(self, name, operation, receive, failed=None):
        def error(message):
            self.feedback.show(message)
            if failed:
                failed()

        def worker():
            try:
                value = operation()
                self.completed.emit(lambda: receive(value))
            except Exception as exc:
                logger.exception("Operazione UI %s fallita", name)
                message = str(exc)
                self.completed.emit(lambda: error(message))

        try:
            self.application.submit(name, worker, "ui_operation_error")
        except Exception as exc:
            logger.exception("Avvio operazione UI fallito")
            error(str(exc))

    def close(self):
        self._closed = True


def choose_files():
    return QFileDialog.getOpenFileNames(
        None, "Seleziona file audio o video", "", MEDIA_FILTER
    )[0]


def export_session(adapter, session_id, fmt, profile="raw"):
    if fmt not in {"txt", "srt", "vtt"}:
        raise ValueError("formato export non supportato")
    target, _ = QFileDialog.getSaveFileName(
        None,
        "Esporta trascrizione",
        str(Path.home() / f"{session_id}.{fmt}"),
        f"{fmt.upper()} (*.{fmt})",
    )
    if target:
        adapter.background(
            "qml-export",
            lambda: adapter.application.export_history_format(
                session_id, target, fmt, profile
            ),
            lambda _: adapter.feedback.show(f"Esportato: {target}"),
        )
