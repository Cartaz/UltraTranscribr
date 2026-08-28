"""Desktop shell hosting the HTML/CSS/JavaScript interface."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDragMoveEvent, QDropEvent, QResizeEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from config.constants import AppMeta, UIConstraints
from core.application_service import ApplicationService
from ui.bridge import BackendBridge, BridgeLogHandler

logger = logging.getLogger(__name__)


class LocalOnlyWebPage(QWebEnginePage):
    """Keep application content local and hand external HTTP(S) links to the OS."""

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
        logger.warning(
            "Navigazione WebEngine bloccata per schema non consentito: %s",
            scheme or "<vuoto>",
        )
        return False

    def createWindow(self, _window_type):
        return self


def configure_local_web_settings(settings: QWebEngineSettings) -> None:
    """Apply the local-only policy shared by the main window and native overlays."""
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
        False,
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
        True,
    )


class DropAwareWebView(QWebEngineView):
    filesDropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _local_files(event) -> list[str]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

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
    def __init__(self, application: ApplicationService) -> None:
        super().__init__()
        self._application = application
        self._tray_icon = None
        self._closing = False
        self._geometry_tracking_ready = False
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._persist_window_geometry)
        self.setWindowTitle(AppMeta.NAME)
        self.setMinimumSize(UIConstraints.MIN_WINDOW_WIDTH, UIConstraints.MIN_WINDOW_HEIGHT)
        desktop = application.desktop_state()
        self.resize(
            max(UIConstraints.MIN_WINDOW_WIDTH, int(desktop["window_width"])),
            max(UIConstraints.MIN_WINDOW_HEIGHT, int(desktop["window_height"])),
        )
        self._bridge = BackendBridge(application, self)
        self._bridge.eventReceived.connect(self._observe_backend_event)
        self._log_handler = BridgeLogHandler(self._bridge)
        logging.getLogger().addHandler(self._log_handler)
        self._web_view = DropAwareWebView(self)
        self._web_page = LocalOnlyWebPage(self._web_view)
        self._web_view.setPage(self._web_page)
        configure_local_web_settings(self._web_page.settings())
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
        self._tray_icon.set_running(self._application.live_active())

    def on_start(self) -> None:
        desktop = self._application.desktop_state()
        self._application.start_live(str(desktop["audio_source"]), str(desktop["sink_name"] or ""), str(desktop["language"]), False)

    def on_stop(self) -> None:
        self._application.stop_all_live(drain=False)
        self._application.cancel_file_queue()

    def force_quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._geometry_save_timer.stop()
        self._persist_window_geometry()
        logging.getLogger().removeHandler(self._log_handler)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        tray_available = self._tray_icon is not None and self._tray_icon.isSystemTrayAvailable()
        if tray_available:
            self._geometry_save_timer.stop()
            self._persist_window_geometry()
            self.hide()
            event.ignore()
            return
        self._closing = True
        self._geometry_save_timer.stop()
        self._persist_window_geometry()
        logging.getLogger().removeHandler(self._log_handler)
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._geometry_tracking_ready and not self._closing:
            self._geometry_save_timer.start(350)

    def _persist_window_geometry(self) -> None:
        width = max(UIConstraints.MIN_WINDOW_WIDTH, int(self.width()))
        height = max(UIConstraints.MIN_WINDOW_HEIGHT, int(self.height()))
        try:
            self._application.persist_window_geometry(width, height)
        except Exception:
            logger.exception("Salvataggio automatico geometria finestra fallito")

    def _observe_backend_event(self, event: str, payload_json: str) -> None:
        del payload_json
        if self._tray_icon is None:
            return
        if event.startswith("live_session_"):
            self._tray_icon.set_running(self._application.live_active())
