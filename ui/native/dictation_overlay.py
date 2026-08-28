"""Non-focusable local-WebEngine status overlay for system-wide Dictation."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from ui.main_window import LocalOnlyWebPage, configure_local_web_settings


class DictationOverlay(QMainWindow):
    """Tiny presentation-only shell; it intentionally has no QWebChannel."""

    WIDTH = 460
    HEIGHT = 76
    BOTTOM_MARGIN = 48

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        self._view = QWebEngineView(self)
        self._page = LocalOnlyWebPage(self._view)
        self._view.setPage(self._page)
        configure_local_web_settings(self._page.settings())
        self._page.setBackgroundColor(QColor(0, 0, 0, 0))
        self.setCentralWidget(self._view)
        path = Path(__file__).resolve().parents[1] / "web" / "dictation_overlay.html"
        self._view.setUrl(QUrl.fromLocalFile(str(path)))
        self.hide()

    def update_state(self, status: str, pending: str = "") -> None:
        del pending
        if status in {"starting", "listening", "finalizing"}:
            self._reposition()
            self.show()
            self.raise_()
        else:
            self.hide()

    def _reposition(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.x() + max(0, (area.width() - self.width()) // 2)
        y = area.bottom() - self.height() - self.BOTTOM_MARGIN
        self.move(x, y)
