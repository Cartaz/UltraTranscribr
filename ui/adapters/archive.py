"""History, recovery, recordings and asynchronous export."""

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot

from ui.adapters.base import Adapter, export_session
from ui.models import RecordModel


class ArchiveAdapter(Adapter):
    changed = Signal()
    deleted = Signal(str)

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self.history = RecordModel(parent=self)
        self.recovery = RecordModel(parent=self)
        self.meetings = RecordModel(parent=self)
        self.profiles = RecordModel(parent=self)
        self._selected = {}
        self._recording = {}
        self._profile = "raw"
        self._query = ""
        self._generation = 0
        self._selection_generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self.refresh)

    @Property("QVariantMap", notify=changed)
    def selected(self):
        return self._selected

    @Property("QVariantMap", notify=changed)
    def recording(self):
        return self._recording

    @Property(str, notify=changed)
    def profile(self):
        return self._profile

    @Property(str, notify=changed)
    def text(self):
        if self._profile != "raw":
            return str(
                (self._selected.get("derived_outputs") or {}).get(self._profile, "")
            )
        return str(self._selected.get("full_text") or self._selected.get("text") or "")

    @Slot(str)
    def search(self, query):
        self._query = query
        self.requestRefresh()

    def requestRefresh(self):
        self._generation += 1
        self._timer.start()

    @Slot()
    def refresh(self):
        self._generation += 1
        generation = self._generation
        query = self._query

        def receive(value):
            if generation != self._generation:
                return
            history, recovery, all_history = value
            self.history.replace(history)
            self.recovery.replace(recovery)
            self.meetings.replace(
                [r for r in all_history if r.get("kind") == "meeting"]
            )

        self.background(
            "qml-history",
            lambda: (
                self.application.search_history(query, 500),
                self.application.list_recovery_audio(),
                self.application.list_history(500),
            ),
            receive,
        )

    @Slot(str)
    def select(self, session_id, profile="raw"):
        self._selection_generation += 1
        generation = self._selection_generation

        def read():
            session = self.application.get_history_session(session_id)
            info = self.application.session_recording_info(session_id)
            if info.get("exists"):
                info["url"] = QUrl.fromLocalFile(str(info["path"])).toString()
            return session, info

        def receive(value):
            if generation == self._selection_generation:
                self._selected = value[0] or {}
                self._recording = value[1]
                self._profile = profile
                self.changed.emit()

        self.background("qml-history-select", read, receive)

    @Slot(str)
    def rename(self, name):
        session_id = self._selected.get("id", "")

        def receive(value):
            if self._selected.get("id") == session_id:
                self._selected["name"] = value
                self.changed.emit()
            self.refresh()

        self.background(
            "qml-rename",
            lambda: self.application.rename_history_session(session_id, name),
            receive,
        )

    @Slot(str)
    def setProfile(self, profile):
        self._profile = profile
        self.changed.emit()

    @Slot(str)
    def generate(self, profile):
        session_id = self._selected.get("id", "")
        generation = self._selection_generation

        def receive(_):
            if (
                generation == self._selection_generation
                and self._selected.get("id") == session_id
            ):
                self.select(session_id, profile)

        self.background(
            "qml-postprocess",
            lambda: self.application.generate_postprocess(session_id, profile),
            receive,
        )

    @Slot(str)
    def export(self, fmt):
        self.attempt(
            lambda: export_session(
                self, self._selected.get("id", ""), fmt, self._profile
            )
        )

    @Slot(str)
    def deleteSession(self, session_id):
        def receive(_):
            if self._selected.get("id") == session_id:
                self._selected = {}
                self._recording = {}
                self._selection_generation += 1
                self.changed.emit()
            self.deleted.emit(session_id)
            self.refresh()

        self.background(
            "qml-history-delete",
            lambda: self.application.delete_history_session(session_id),
            receive,
        )

    @Slot()
    def deleteRecording(self):
        session_id = self._selected.get("id", "")
        self.background(
            "qml-recording-delete",
            lambda: self.application.delete_session_recording(session_id),
            lambda _: self.select(session_id),
        )

    @Slot(str)
    def recover(self, path):
        self.attempt(lambda: self.application.start_recovery(path))

    @Slot(str)
    def deleteRecovery(self, path):
        self.background(
            "qml-recovery-delete",
            lambda: self.application.delete_recovery(path),
            lambda _: self.refresh(),
        )
