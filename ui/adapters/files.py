"""File queue and local file selection."""

from PySide6.QtCore import Property, QUrl, Signal, Slot
from ui.adapters.base import Adapter, choose_files
from ui.models import RecordModel


class FileAdapter(Adapter):
    changed = Signal()

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self.queue = RecordModel(parent=self)
        self._paths = []
        self._text = ""
        self._status = "idle"
        self._progress = 0.0
        self._busy = False

    @Property(str, notify=changed)
    def selection(self):
        return " · ".join(self._paths)

    @Property(str, notify=changed)
    def text(self):
        return self._text

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy or any(
            r.get("status") in {"queued", "starting", "running", "cancelling"}
            for r in self.queue.rows()
        )

    def set_paths(self, paths):
        rows = self.attempt(lambda: self.application.existing_files(paths))
        if rows:
            self._paths = rows
            self.changed.emit()
        else:
            self.feedback.show("Seleziona almeno un file locale esistente")

    @Slot()
    def choose(self):
        paths = choose_files()
        if paths:
            self.set_paths(paths)

    @Slot("QVariantList")
    def dropFiles(self, urls):
        self.set_paths(
            [u.toLocalFile() for value in urls if (u := QUrl(value)).isLocalFile()]
        )

    @Slot(bool, bool)
    def start(self, song, isolate):
        if not self._paths:
            self.feedback.show("Seleziona un file esistente")
            return
        jobs = self.attempt(
            lambda: self.application.enqueue_files(
                self._paths,
                language="",
                model_size="",
                song_mode=song,
                isolate_vocals=isolate,
            )
        )
        if jobs is not None:
            self.queue.replace(jobs)
            self._text = ""
            self.changed.emit()

    @Slot()
    def cancel(self):
        jobs = self.attempt(self.application.cancel_file_queue)
        if jobs is not None:
            self.queue.replace(jobs)
            self.changed.emit()

    @Slot()
    def clearFinished(self):
        jobs = self.attempt(self.application.clear_finished_file_queue)
        if jobs is not None:
            self.queue.replace(jobs)
            self.changed.emit()

    @Slot()
    def clearText(self):
        self._text = ""
        self.changed.emit()

    def handle_event(self, name, value):
        if name == "file_queue_changed":
            self.queue.replace(value or [])
        elif name == "file_queue_job_updated":
            self.queue.upsert(value)
        elif name == "file_transcriber_status_changed":
            self._status = str(value)
            self._busy = self._status not in {"idle", "completed", "stopped", "error"}
        elif name == "file_transcriber_progress":
            self._progress = float(value or 0)
        elif name == "file_transcriber_full_text":
            self._text = str(value or "")
        elif name == "file_transcriber_new_text":
            self._text += str(value or "") + "\n"
        elif name in {"file_transcriber_completed", "file_transcriber_error"}:
            self._busy = False
        self.changed.emit()
