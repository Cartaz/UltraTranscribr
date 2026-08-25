"""Desktop shell hosting the HTML/CSS/JavaScript interface."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QResizeEvent,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from config.constants import AppMeta, UIConstraints
from core.app_controller import AppController
from ui.bridge import BridgeLogHandler
from ui.phase10_bridge import Phase10BackendBridge

logger = logging.getLogger(__name__)


class LocalOnlyWebPage(QWebEnginePage):
    """Keep application content local and hand external web links to the OS."""

    _LOCAL_SCHEMES = {"about", "file", "qrc"}
    _EXTERNAL_SCHEMES = {"http", "https"}

    def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:
        scheme = url.scheme().lower()
        if url.isLocalFile() or scheme in self._LOCAL_SCHEMES:
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)
        if scheme in self._EXTERNAL_SCHEMES:
            logger.info("Apertura URL esterno nel browser di sistema: %s", url.toString())
            QDesktopServices.openUrl(url)
            return False
        logger.warning("Navigazione WebEngine bloccata per schema non consentito: %s", scheme or "<vuoto>")
        return False

    def createWindow(self, _window_type):
        # Route target=_blank through this page so acceptNavigationRequest keeps
        # the same local-only policy instead of spawning an unmanaged WebEngine.
        return self


class DropAwareWebView(QWebEngineView):
    """Capture local file URLs before Chromium attempts to navigate to them."""

    filesDropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _local_files(event) -> list[str]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        paths: list[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file():
                paths.append(str(path))
        return paths

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._local_files(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._local_files(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._local_files(event)
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


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

        self._bridge = Phase10BackendBridge(controller, self)
        self._bridge.eventReceived.connect(self._observe_backend_event)

        self._log_handler = BridgeLogHandler(self._bridge)
        logging.getLogger().addHandler(self._log_handler)

        self._web_view = DropAwareWebView(self)
        self._web_page = LocalOnlyWebPage(self._web_view)
        self._web_view.setPage(self._web_page)
        web_settings = self._web_page.settings()
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        self._web_view.filesDropped.connect(self._bridge.emitDroppedFiles)
        self.setCentralWidget(self._web_view)

        channel = QWebChannel(self._web_page)
        channel.registerObject("backend", self._bridge)
        self._web_page.setWebChannel(channel)
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
        self._bridge.cancelFileQueue()

    def force_quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._geometry_save_timer.stop()
        self._persist_window_geometry()
        try:
            self._shutdown_runtime()
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
                self._shutdown_runtime()
            finally:
                logging.getLogger().removeHandler(self._log_handler)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._geometry_tracking_ready and not self._closing:
            self._geometry_save_timer.start(350)

    def _shutdown_runtime(self) -> None:
        self._controller.shutdown()

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
