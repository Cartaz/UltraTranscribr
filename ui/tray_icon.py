"""System tray integration for UltraTranscribr."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    """Own the complete tray surface and expose a narrow lifecycle contract."""

    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None, icon_path: str | None = None) -> None:
        icon = QIcon(icon_path) if icon_path else QIcon()
        if icon.isNull():
            app = QApplication.instance()
            if app is not None:
                icon = app.windowIcon()
        if icon.isNull():
            icon = QIcon.fromTheme("audio-input-microphone")

        super().__init__(icon, parent)
        self.setToolTip("UltraTranscribr")

        # QSystemTrayIcon does not take ownership of its context menu. Keep a
        # strong reference for the complete tray lifetime.
        self._menu = QMenu()
        self._show_action = QAction("Apri UltraTranscribr", self._menu)
        self._start_action = QAction("Avvia trascrizione live", self._menu)
        self._stop_action = QAction("Ferma trascrizione", self._menu)
        self._quit_action = QAction("Esci", self._menu)
        self._stop_action.setEnabled(False)

        self._menu.addAction(self._show_action)
        self._menu.addSeparator()
        self._menu.addAction(self._start_action)
        self._menu.addAction(self._stop_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)
        self.setContextMenu(self._menu)

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

    def ready_for_background(self) -> bool:
        """Return whether hiding the last window still leaves a usable exit path."""
        return bool(
            self.isSystemTrayAvailable()
            and self.isVisible()
            and not self.icon().isNull()
            and self.contextMenu() is self._menu
        )

    def log_readiness(self) -> None:
        logger.info(
            "System tray — available=%s visible=%s icon=%s menu=%s ready=%s",
            self.isSystemTrayAvailable(),
            self.isVisible(),
            not self.icon().isNull(),
            self.contextMenu() is self._menu,
            self.ready_for_background(),
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window_requested.emit()
