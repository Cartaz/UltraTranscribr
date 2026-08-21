"""Desktop shell hosting the HTML/CSS/JavaScript interface."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from config.constants import AppMeta, UIConstraints
from core.app_controller import AppController
from ui.bridge import BridgeLogHandler
from ui.multi_session_bridge import MultiSessionBackendBridge

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._controller = controller
        self._tray_icon = None
        self._closing = False
        self._geometry_tracking_ready = False
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._persist_window_geometry)

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

        self._bridge = MultiSessionBackendBridge(controller, self)
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
        self._geometry_tracking_ready = True

    def set_tray_icon(self, tray_icon) -> None:
        self._tray_icon = tray_icon
        self._tray_icon.set_running(self._controller.active_live_count() > 0)

    def on_start(self) -> None:
        settings = self._controller.settings
        self._bridge.startLive(
            settings.audio_source,
            settings.sink_name or "",
            settings.language,
        )

    def on_stop(self) -> None:
        self._bridge.stopAllLive()
        self._bridge.stopFile()

    def force_quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._geometry_save_timer.stop()
        self._persist_window_geometry()
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
            self._geometry_save_timer.stop()
            self._persist_window_geometry()
            try:
                self._controller.shutdown()
            finally:
                logging.getLogger().removeHandler(self._log_handler)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._geometry_tracking_ready and not self._closing:
            self._geometry_save_timer.start(350)

    def _persist_window_geometry(self) -> None:
        width = max(UIConstraints.MIN_WINDOW_WIDTH, int(self.width()))
        height = max(UIConstraints.MIN_WINDOW_HEIGHT, int(self.height()))
        current = self._controller.settings
        if current.window_width == width and current.window_height == height:
            return
        try:
            self._controller.update_settings(
                window_width=width,
                window_height=height,
            )
        except Exception:
            logger.exception("Salvataggio automatico geometria finestra fallito")

    def _observe_backend_event(self, event: str, payload_json: str) -> None:
        del payload_json
        if self._tray_icon is None:
            return
        if event.startswith("live_session_"):
            self._tray_icon.set_running(self._controller.active_live_count() > 0)
