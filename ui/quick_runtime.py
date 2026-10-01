"""Focused application adapters and queued event marshalling."""

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot

from ui.adapters.archive import ArchiveAdapter
from ui.adapters.base import Feedback
from ui.adapters.files import FileAdapter
from ui.adapters.live import LiveAdapter
from ui.adapters.meeting import MeetingAdapter
from ui.adapters.settings import SettingsAdapter
from ui.adapters.sources import SourcesAdapter
from ui.events import PRESENTATION_EVENTS


class QuickRuntime(QObject):
    eventArrived = Signal(str, object)
    logArrived = Signal(str)
    changed = Signal()

    def __init__(self, application, parent=None):
        super().__init__(parent)
        self.application = application
        self.feedback = Feedback(self)
        self.sources = SourcesAdapter(application, self.feedback, self)
        self.live = LiveAdapter(application, self.feedback, self.sources, self)
        self.files = FileAdapter(application, self.feedback, self)
        self.settings = SettingsAdapter(application, self.feedback, self)
        self.archive = ArchiveAdapter(application, self.feedback, self)
        self.meeting = MeetingAdapter(application, self.feedback, self)
        self.archive.deleted.connect(self.meeting.clearDeleted)
        self._status = "Standby"
        self._log = ""
        self._diagnostics = "Nessuna diagnostica eseguita."
        self._closed = False
        self._handlers = {}
        self.eventArrived.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.logArrived.connect(self._append_log, Qt.ConnectionType.QueuedConnection)
        for adapter in (self.live, self.files, self.settings, self.meeting):
            adapter.changed.connect(self.changed)
        for name in (*PRESENTATION_EVENTS, "ui_operation_error", "dictation_error"):
            handler = lambda value, event=name: self.eventArrived.emit(event, value)
            self._handlers[name] = handler
            application.subscribe(name, handler)
        self._hydrate(application.bootstrap_snapshot())
        QTimer.singleShot(0, self._start)

    def _hydrate(self, boot):
        self.settings.hydrate(boot.get("settings", {}))
        self.settings.models.replace(boot.get("models", []))
        self.sources._source = boot.get("settings", {}).get("audio_source", "system")
        self.sources.set_devices(boot.get("devices", []))
        self.sources.set_streams(boot.get("playbackStreams", []))
        self.live.hydrate(boot.get("liveSessions", []))
        self.files.queue.replace(boot.get("fileQueue", []))
        self.files._busy = boot.get("runtime", {}).get("fileRunning", False)
        self.meeting.queue.replace(boot.get("meetingQueue", []))
        self.meeting.set_runtime(boot.get("meetingRuntime"))
        self.archive.profiles.replace(
            [{"id": "raw", "label": "Originale"}, *boot.get("postprocessProfiles", [])]
        )
        self._log = self.application.read_log_tail(160)
        self._status = (
            "Pronto" if boot.get("runtime", {}).get("backendRunning") else "Standby"
        )

    def _start(self):
        if not self._closed:
            self.settings.attempt(self.application.preload_model_if_requested)
            self.archive.refresh()
            self.sources.refresh()

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def busy(self):
        return (
            self.live.activeCount > 0
            or self.files.busy
            or self.meeting.busy
            or any(
                r.get("status") in {"queued", "starting", "running", "cancelling"}
                for r in self.meeting.queue.rows()
            )
        )

    @Property(str, notify=changed)
    def logText(self):
        return self._log

    @Property(str, notify=changed)
    def diagnostics(self):
        return self._diagnostics

    @Slot(str)
    def _append_log(self, line):
        if not self._closed:
            self._log = "\n".join((self._log + "\n" + line).splitlines()[-1000:])
            self.changed.emit()

    @Slot()
    def refreshLog(self):
        self.archive.background(
            "qml-log", lambda: self.application.read_log_tail(200), self._set_log
        )

    def _set_log(self, value):
        self._log = value
        self.changed.emit()

    @Slot()
    def runDiagnostics(self):
        self.archive.attempt(self.application.run_audio_diagnostics)

    @Slot(str, object)
    def _event(self, name, value):
        if self._closed:
            return
        if name.startswith("live_session_"):
            self.live.handle_event(name, value)
        elif name.startswith("file_"):
            self.files.handle_event(name, value)
        elif name.startswith("meeting_"):
            self.meeting.handle_event(name, value)
        if name.startswith("model_") or name == "config_changed":
            self.settings.handle_event(name, value)
        if (
            name == "config_changed"
            and isinstance(value, dict)
            and value.get("audio_source")
        ):
            self.sources.setSource(value["audio_source"])
        if name in {"history_changed", "meeting_completed", "recovery_audio_saved"}:
            self.archive.requestRefresh()
        if name == "audio_devices_changed":
            self.sources.set_devices(value)
        elif name == "playback_streams_changed":
            self.sources.set_streams(value)
        elif name == "audio_source_health_changed":
            self.sources.set_health(value)
        elif name == "backend_status_changed":
            self._status = {
                "standby": "Standby",
                "ready": "Pronto",
                "error": "Errore",
                "starting_backend": "Avvio backend",
                "downloading_model": "Download modello",
                "preparing_vad": "Preparazione VAD",
                "configuring_backend": "Configurazione backend",
                "switching_model": "Cambio modello",
            }.get(str(value), str(value))
        elif name == "audio_diagnostics":
            self._diagnostics = str(value)
        if name.endswith("_error"):
            self.feedback.show(
                value.get("error", value) if isinstance(value, dict) else value
            )
        self.changed.emit()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for name, handler in self._handlers.items():
            self.application.unsubscribe(name, handler)
        self._handlers.clear()
        for adapter in (
            self.sources,
            self.live,
            self.files,
            self.settings,
            self.archive,
            self.meeting,
        ):
            adapter.close()
