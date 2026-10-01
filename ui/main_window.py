"""Qt Quick desktop shell, native tray and deterministic window lifecycle."""

from __future__ import annotations
import logging
from pathlib import Path
import shiboken6
from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication, QMessageBox
from config.constants import AppMeta, UIConstraints
from core.application_service import ApplicationService
from ui.quick_runtime import QuickRuntime

logger = logging.getLogger(__name__)


def clamp_window_geometry(desired: QRect, available_rects: list[QRect]) -> QRect:
    """Clamp a persisted geometry to a usable screen while respecting minimum size."""
    width = max(UIConstraints.MIN_WINDOW_WIDTH, int(desired.width()))
    height = max(UIConstraints.MIN_WINDOW_HEIGHT, int(desired.height()))
    normalized = QRect(int(desired.x()), int(desired.y()), width, height)
    if not available_rects:
        return normalized

    def intersection_area(screen_rect: QRect) -> int:
        intersection = normalized.intersected(screen_rect)
        return max(0, intersection.width()) * max(0, intersection.height())

    target = max(available_rects, key=intersection_area)
    if intersection_area(target) == 0:
        # Callers provide the primary screen first, so monitor removal or a stale
        # off-screen position recovers deterministically to the primary display.
        target = available_rects[0]

    max_width = max(UIConstraints.MIN_WINDOW_WIDTH, int(target.width()))
    max_height = max(UIConstraints.MIN_WINDOW_HEIGHT, int(target.height()))
    width = min(width, max_width)
    height = min(height, max_height)

    min_x = int(target.x())
    min_y = int(target.y())
    max_x = int(target.x() + target.width() - width)
    max_y = int(target.y() + target.height() - height)
    x = min_x if max_x < min_x else min(max(normalized.x(), min_x), max_x)
    y = min_y if max_y < min_y else min(max(normalized.y(), min_y), max_y)
    return QRect(x, y, width, height)


class QuickLogHandler(logging.Handler):
    def __init__(self, runtime):
        super().__init__(logging.INFO)
        self.runtime = runtime

    def emit(self, record):
        self.runtime.logArrived.emit(
            f"[{record.levelname}] {record.name}: {record.getMessage()}"
        )


class MainWindow(QObject):
    def __init__(self, application: ApplicationService):
        super().__init__()
        self._application = application
        self._tray_icon = None
        self._closing = False
        self._meeting_review_dirty = False
        self._geometry_tracking_ready = False
        self._normal_geometry = QRect()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._persist_window_geometry)
        self.runtime = QuickRuntime(application, self)
        self.runtime.meeting.dirtyChanged.connect(self._set_meeting_review_dirty)
        self.runtime.live.changed.connect(self._observe_backend_event)
        self._engine = QQmlApplicationEngine(self)
        context = self._engine.rootContext()
        objects = {
            "runtime": self.runtime,
            "feedback": self.runtime.feedback,
            "appVersion": AppMeta.VERSION,
        }
        for name in ("sources", "live", "files", "settings", "archive", "meeting"):
            objects[name] = getattr(self.runtime, name)
        objects.update(
            audioDevices=self.runtime.sources.devices,
            playbackStreams=self.runtime.sources.streams,
            microphones=self.runtime.sources.microphones,
            monitors=self.runtime.sources.monitors,
            liveSessions=self.runtime.live.sessions,
            liveGroups=self.runtime.live.groups,
            fileQueue=self.runtime.files.queue,
            historyModel=self.runtime.archive.history,
            recoveryModel=self.runtime.archive.recovery,
            meetingsModel=self.runtime.archive.meetings,
            postprocessProfiles=self.runtime.archive.profiles,
            whisperModels=self.runtime.settings.models,
            meetingSources=self.runtime.meeting.sources,
            meetingDrafts=self.runtime.meeting.drafts,
            meetingQueue=self.runtime.meeting.queue,
            meetingSegments=self.runtime.meeting.segments,
            meetingSpeakers=self.runtime.meeting.speakers,
            meetingTracks=self.runtime.meeting.tracks,
        )
        for name, value in objects.items():
            context.setContextProperty(name, value)
        path = Path(__file__).resolve().parent / "qml" / "Main.qml"
        self._engine.load(QUrl.fromLocalFile(str(path)))
        if not self._engine.rootObjects():
            self.runtime.close()
            raise RuntimeError(f"Impossibile caricare la UI QML: {path}")
        self._window = self._engine.rootObjects()[0]
        if not isinstance(self._window, QQuickWindow):
            self.runtime.close()
            raise TypeError("La UI deve creare una QQuickWindow")
        self._window.installEventFilter(self)
        self._restore_window_geometry(application.desktop_state())
        self._geometry_tracking_ready = True
        self._log_handler = QuickLogHandler(self.runtime)
        logging.getLogger().addHandler(self._log_handler)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._prepare_shutdown)

    @staticmethod
    def _available_screen_rects():
        primary = QApplication.primaryScreen()
        screens = QApplication.screens()
        if primary in screens:
            screens = [primary, *[s for s in screens if s is not primary]]
        return [s.availableGeometry() for s in screens]

    def _restore_window_geometry(self, desktop):
        width = max(UIConstraints.MIN_WINDOW_WIDTH, int(desktop["window_width"]))
        height = max(UIConstraints.MIN_WINDOW_HEIGHT, int(desktop["window_height"]))
        if desktop.get("window_x") is None or desktop.get("window_y") is None:
            self._window.resize(width, height)
        else:
            self._window.setGeometry(
                clamp_window_geometry(
                    QRect(
                        int(desktop["window_x"]),
                        int(desktop["window_y"]),
                        width,
                        height,
                    ),
                    self._available_screen_rects(),
                )
            )
        self._normal_geometry = self._window.geometry()

    def dispose(self):
        self._prepare_shutdown()
        if shiboken6.isValid(self._engine):
            self._window.hide()
            shiboken6.delete(self._engine)

    def show(self):
        self._window.show()

    def hide(self):
        self._window.hide()

    def raise_(self):
        self._window.raise_()

    def activateWindow(self):
        self._window.requestActivate()

    def setWindowIcon(self, icon):
        self._window.setIcon(icon)

    def resize(self, width, height):
        self._window.resize(width, height)

    def close(self):
        return self._window.close()

    def set_tray_icon(self, tray):
        self._tray_icon = tray
        tray.set_running(self._application.live_active())

    def on_start(self):
        desktop = self._application.desktop_state()
        self.runtime.live.attempt(
            lambda: self._application.start_live(
                str(desktop["audio_source"]),
                str(desktop["sink_name"] or ""),
                str(desktop["language"]),
                False,
            )
        )

    def on_stop(self):
        self.runtime.live.stopAll(False)
        self.runtime.files.cancel()

    def _set_meeting_review_dirty(self, dirty):
        self._meeting_review_dirty = bool(dirty)

    def _prepare_shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._geometry_save_timer.stop()
        self._persist_window_geometry()
        logging.getLogger().removeHandler(self._log_handler)
        self.runtime.close()

    def _confirm_discard_unsaved_meeting_review(self):
        if not self._meeting_review_dirty:
            return True
        return (
            QMessageBox.warning(
                None,
                "Modifiche non salvate",
                "Ci sono correzioni della riunione non ancora salvate. Usa “Salva tutto” per conservarle.\n\nUscire comunque senza salvarle?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def force_quit(self):
        if self._closing or not self._confirm_discard_unsaved_meeting_review():
            return
        self._prepare_shutdown()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        tray_ready = bool(
            self._tray_icon is not None and self._tray_icon.ready_for_background()
        )
        if tray_ready:
            self._geometry_save_timer.stop()
            self._persist_window_geometry()
            self.hide()
            event.ignore()
            return
        if not self._confirm_discard_unsaved_meeting_review():
            event.ignore()
            return
        if self._tray_icon is not None:
            logger.warning(
                "System tray non utilizzabile: chiusura finestra esegue lo shutdown"
            )
        self._prepare_shutdown()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() == QEvent.Type.Close:
                self.closeEvent(event)
                return not event.isAccepted()
            if event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                self._schedule_geometry_save()
        return super().eventFilter(watched, event)

    def _schedule_geometry_save(self):
        if self._geometry_tracking_ready and not self._closing:
            if self._window.windowState() not in {
                Qt.WindowState.WindowMaximized,
                Qt.WindowState.WindowFullScreen,
            }:
                self._normal_geometry = self._window.geometry()
            self._geometry_save_timer.start(350)

    def _persist_window_geometry(self):
        rect = (
            self._normal_geometry
            if self._normal_geometry.isValid()
            else self._window.geometry()
        )
        try:
            self._application.persist_window_geometry(
                rect.x(),
                rect.y(),
                max(UIConstraints.MIN_WINDOW_WIDTH, rect.width()),
                max(UIConstraints.MIN_WINDOW_HEIGHT, rect.height()),
            )
        except Exception:
            logger.exception("Salvataggio geometria finestra fallito")

    def _observe_backend_event(self):
        if self._tray_icon is not None:
            self._tray_icon.set_running(self._application.live_active())
