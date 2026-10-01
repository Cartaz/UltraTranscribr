"""Local Qt Quick dictation overlay that never steals keyboard focus."""

from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


class DictationOverlay(QObject):
    WIDTH = 460
    HEIGHT = 76
    BOTTOM_MARGIN = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = QQmlApplicationEngine(self)
        path = Path(__file__).resolve().parents[1] / "qml" / "DictationOverlay.qml"
        self._engine.load(QUrl.fromLocalFile(str(path)))
        if not self._engine.rootObjects():
            raise RuntimeError(f"Impossibile caricare overlay QML: {path}")
        self._window = self._engine.rootObjects()[0]

    def update_state(self, status, pending=""):
        if not shiboken6.isValid(self._engine):
            return
        if status in {"starting", "listening", "finalizing"}:
            self._reposition()
            self._window.show()
            self._window.raise_()
        else:
            self.hide()

    def hide(self):
        if shiboken6.isValid(self._engine):
            self._window.hide()

    def close(self):
        if shiboken6.isValid(self._engine):
            self._window.hide()
            shiboken6.delete(self._engine)

    def isVisible(self):
        return shiboken6.isValid(self._engine) and self._window.isVisible()

    def _reposition(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or self._window.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self._window.setPosition(
            area.x() + max(0, (area.width() - self.WIDTH) // 2),
            area.bottom() - self.HEIGHT - self.BOTTOM_MARGIN,
        )
