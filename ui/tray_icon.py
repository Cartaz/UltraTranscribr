"""System tray integration for UltraTranscribr."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QSystemTrayIcon):
    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None, icon_path: str | None = None) -> None:
        super().__init__(QIcon(icon_path) if icon_path else QIcon(), parent)
        self.setToolTip("UltraTranscribr")

        menu = QMenu()
        self._show_action = QAction("Apri UltraTranscribr", menu)
        self._start_action = QAction("Avvia trascrizione live", menu)
        self._stop_action = QAction("Ferma trascrizione", menu)
        self._quit_action = QAction("Esci", menu)
        self._stop_action.setEnabled(False)

        menu.addAction(self._show_action)
        menu.addSeparator()
        menu.addAction(self._start_action)
        menu.addAction(self._stop_action)
        menu.addSeparator()
        menu.addAction(self._quit_action)
        self.setContextMenu(menu)

        self._show_action.triggered.connect(self.show_window_requested.emit)
        self._quit_action.triggered.connect(self.quit_requested.emit)
        self.activated.connect(self._on_activated)

    def connect_start_action(self, callback: Callable[[], None]) -> None:
        self._start_action.triggered.connect(callback)

    def connect_stop_action(self, callback: Callable[[], None]) -> None:
        self._stop_action.triggered.connect(callback)

    def set_running(self, running: bool) -> None:
        self._start_action.setEnabled(not running)
        self._stop_action.setEnabled(running)
        suffix = " — trascrizione attiva" if running else ""
        self.setToolTip(f"UltraTranscribr{suffix}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window_requested.emit()
