"""Desktop shell hosting the HTML/CSS/JavaScript interface."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from config.constants import AppMeta, UIConstraints
from core.app_controller import AppController
from ui.bridge import BackendBridge, BridgeLogHandler

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._tray_icon = None
        self._closing = False

        self.setWindowTitle(AppMeta.NAME)
        self.setMinimumSize(
            UIConstraints.MIN_WINDOW_WIDTH,
            UIConstraints.MIN_WINDOW_HEIGHT,
        )
        settings = controller.settings
        self.resize(
            max(UIConstraints.MIN_WINDOW_WIDTH, settings.window_width),
            max(UIConstraints.MIN_WINDOW_HEIGHT, settings.window_height),
        )

        self._bridge = BackendBridge(controller, self)
        self._bridge.windowResizeRequested.connect(self._resize_from_settings)
        self._bridge.eventReceived.connect(self._observe_backend_event)

        self._log_handler = BridgeLogHandler(self._bridge)
        logging.getLogger().addHandler(self._log_handler)

        self._web_view = QWebEngineView(self)
        self.setCentralWidget(self._web_view)

        channel = QWebChannel(self._web_view.page())
        channel.registerObject("backend", self._bridge)
        self._web_view.page().setWebChannel(channel)
        self._channel = channel

        index_path = Path(__file__).resolve().parent / "web" / "index.html"
        self._web_view.setUrl(QUrl.fromLocalFile(str(index_path)))

    def set_tray_icon(self, tray_icon) -> None:
        self._tray_icon = tray_icon
        self._tray_icon.set_running(
            self._controller.is_running() or self._controller.is_draining()
        )

    def on_start(self) -> None:
        settings = self._controller.settings
        self._bridge.startLive(settings.audio_source, settings.sink_name or "", settings.language)

    def on_stop(self) -> None:
        self._bridge.stopLive()
        self._bridge.stopFile()

    def force_quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._controller.shutdown()
        finally:
            logging.getLogger().removeHandler(self._log_handler)
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing:
            self._closing = True
            try:
                self._controller.shutdown()
            finally:
                logging.getLogger().removeHandler(self._log_handler)
        event.accept()

    def _resize_from_settings(self, width: int, height: int) -> None:
        self.resize(
            max(UIConstraints.MIN_WINDOW_WIDTH, width),
            max(UIConstraints.MIN_WINDOW_HEIGHT, height),
        )

    def _observe_backend_event(self, event: str, payload_json: str) -> None:
        if self._tray_icon is None:
            return
        if event == "process_started":
            self._tray_icon.set_running(True)
        elif event in ("process_stopped", "transcriber_drained"):
            self._tray_icon.set_running(False)
