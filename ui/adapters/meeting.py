"""Meeting input drafts and review, retaining edits through delegate recycling."""

import time

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot

from ui.adapters.base import Adapter, choose_files, export_session
from ui.models import RecordModel


class MeetingAdapter(Adapter):
    changed = Signal()
    dirtyChanged = Signal(bool)

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self.sources = RecordModel(
            [
                {
                    "source": "microphone",
                    "selected_input": "",
                    "stream_id": None,
                    "label": "",
                }
            ],
            self,
        )
        self.drafts = RecordModel(parent=self)
        self.queue = RecordModel(parent=self)
        self.segments = RecordModel(parent=self)
        self.speakers = RecordModel(parent=self)
        self.tracks = RecordModel(parent=self)
        self._runtime = {}
        self._review = {}
        self._edits = {}
        self._audio = ""
        self._writing = False
        self._generation = 0
        self._runtime_clock = time.monotonic()
        self._model_progress = {}
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.changed)
        self._timer.start()

    @Property("QVariantMap", notify=changed)
    def runtime(self):
        return self._runtime

    @Property("QVariantMap", notify=changed)
    def review(self):
        return self._review

    @Property("QVariantMap", notify=changed)
    def modelProgress(self):
        return self._model_progress

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._runtime) and self._runtime.get("status") not in {
            "completed",
            "error",
            "cancelled",
            "interrupted",
        }

    @Property(bool, notify=changed)
    def dirty(self):
        return bool(self._edits)

    @Property(bool, notify=changed)
    def saving(self):
        return self._writing

    @Property(str, notify=changed)
    def audioUrl(self):
        return self._audio

    @Property(str, notify=changed)
    def duration(self):
        seconds = float(self._runtime.get("duration_s") or 0)
        if self._runtime.get("status") == "recording":
            seconds += time.monotonic() - self._runtime_clock
        seconds = max(0, int(seconds))
        return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"

    @Slot()
    def addSource(self):
        if self.sources.count < 8:
            self.sources.append(
                {
                    "source": "microphone",
                    "selected_input": "",
                    "stream_id": None,
                    "label": "",
                }
            )

    @Slot(int)
    def removeSource(self, index):
        if self.sources.count > 1:
            self.sources.remove(index)

    @Slot(int, str, str)
    def editSource(self, index, key, value):
        if key not in {"source", "selected_input", "label"}:
            return

        def edit():
            fields = {key: value}
            if key == "source":
                fields.update(selected_input="", stream_id=None)
            if key == "selected_input":
                fields["stream_id"] = (
                    int(value)
                    if value and self.sources.get(index).get("source") == "application"
                    else None
                )
            self.sources.update(index, **fields)

        self.attempt(edit)

    @Slot(str, int)
    def choose(self, language, speakers):
        paths = choose_files()
        if paths:
            self._set_files(paths, language, speakers)

    def _set_files(self, paths, language, speakers):
        values = self.attempt(lambda: self.application.existing_files(paths))
        if values:
            self.drafts.replace(
                [
                    {"path": p, "language": language, "num_speakers": speakers}
                    for p in values
                ]
            )

    @Slot("QVariantList", str, int)
    def dropFiles(self, urls, language, speakers):
        self._set_files(
            [u.toLocalFile() for value in urls if (u := QUrl(value)).isLocalFile()],
            language,
            speakers,
        )

    @Slot(int, str, "QVariant")
    def editDraft(self, index, key, value):
        if key in {"language", "num_speakers"}:
            self.attempt(lambda: self.drafts.update(index, **{key: value}))

    @Slot(int)
    def removeDraft(self, index):
        self.drafts.remove(index)

    @Slot(bool, str, int)
    def start(self, from_file, language, speakers):
        if self.dirty or self._writing:
            self.feedback.show("Salva le correzioni prima di avviare una riunione")
            return
        if from_file:
            rows = self.attempt(
                lambda: self.application.enqueue_meeting_files(self.drafts.rows())
            )
            if rows is not None:
                self.queue.replace(rows)
        else:
            value = self.attempt(
                lambda: self.application.start_meeting_realtime(
                    self.sources.rows(),
                    language=language or None,
                    num_speakers=speakers,
                )
            )
            if value:
                self.set_runtime(value)

    @Slot()
    def finish(self):
        self.attempt(self.application.finish_meeting)

    @Slot()
    def cancel(self):
        self.attempt(self.application.cancel_meeting)

    @Slot()
    def cancelQueue(self):
        rows = self.attempt(self.application.cancel_meeting_queue)
        if rows is not None:
            self.queue.replace(rows)

    @Slot()
    def clearQueue(self):
        rows = self.attempt(self.application.clear_finished_meeting_queue)
        if rows is not None:
            self.queue.replace(rows)

    def set_runtime(self, value):
        self._runtime = value or {}
        self._runtime_clock = time.monotonic()
        self.changed.emit()

    @Slot(str)
    def clearDeleted(self, session_id):
        if self._review.get("id") == session_id:
            self._generation += 1
            self._audio = ""
            self._load_review({})

    @Slot(str)
    def select(self, session_id):
        if self.dirty or self._writing:
            self.feedback.show(
                "Salva tutto o annulla le correzioni prima di cambiare riunione"
            )
            return
        self._generation += 1
        generation = self._generation

        def read():
            value = self.application.get_meeting(session_id)
            path = self.application.meeting_audio_path(session_id)
            return value, QUrl.fromLocalFile(path).toString() if path else ""

        def receive(value):
            if generation == self._generation and not self.dirty and not self._writing:
                self._audio = value[1]
                self._load_review(value[0] or {})

        self.background("qml-meeting-select", read, receive)

    def _load_review(self, value, preserve_edits=False):
        same = value.get("id") == self._review.get("id")
        edits = dict(self._edits) if same and preserve_edits else {}
        self._review = value
        metadata = value.get("meeting") or {}
        names = metadata.get("speaker_names") or {}
        ids = {key for key in names if key.startswith("SPEAKER_")}
        rows = []
        for index, item in enumerate(metadata.get("review_segments") or []):
            speaker = (
                item.get("speaker_override") or item.get("speaker_id") or "UNKNOWN"
            )
            if speaker.startswith("SPEAKER_"):
                ids.add(speaker)
            rows.append(
                {
                    **item,
                    "index": index,
                    "speaker": speaker,
                    "speaker_name": names.get(speaker, speaker),
                    "speaker_choice": item.get("speaker_override") or "",
                    "overlap": len(item.get("overlap_speakers") or []) > 1,
                    "draft_text": edits.get(index, item.get("text", "")),
                    "dirty": index in edits,
                }
            )
        options = [{"value": s, "label": names.get(s, s)} for s in sorted(ids)]
        for row in rows:
            automatic = names.get(
                row.get("speaker_id"), row.get("speaker_id") or "Speaker ?"
            )
            row["speaker_options"] = [
                {"value": "", "label": f"Automatico · {automatic}"},
                *options,
            ]
        if same and self.segments.count == len(rows):
            for index, row in enumerate(rows):
                self.segments.update(index, **row)
        else:
            self.segments.replace(rows)
        previous = (
            {r["id"]: r.get("draft_name") for r in self.speakers.rows()} if same else {}
        )
        self.speakers.replace(
            [
                {"id": s, "name": names.get(s, s), "draft_name": previous.get(s)}
                for s in sorted(ids)
            ]
        )
        self.tracks.replace((metadata.get("acquisition") or {}).get("sources") or [])
        self._edits = edits
        self.dirtyChanged.emit(self.dirty)
        self.changed.emit()

    @Slot(int, str)
    def editText(self, index, text):
        row = self.segments.get(index)
        if not row:
            return
        if text == str(row.get("text") or ""):
            self._edits.pop(index, None)
        else:
            self._edits[index] = text
        self.segments.update(index, draft_text=text, dirty=index in self._edits)
        self.dirtyChanged.emit(self.dirty)
        self.changed.emit()

    @Slot(int, str)
    def editSpeakerName(self, index, name):
        self.speakers.update(index, draft_name=name)

    def _write(self, operation, edits=None, speaker=None):
        if self._writing:
            return
        session_id = self._review["id"]
        self._writing = True
        self.changed.emit()

        def finish():
            self._writing = False
            self.changed.emit()

        def receive(value):
            try:
                if self._review.get("id") != session_id:
                    return
                for index, saved in (edits or {}).items():
                    if self._edits.get(index) == saved:
                        self._edits.pop(index, None)
                if speaker:
                    for index, row in enumerate(self.speakers.rows()):
                        if (
                            row["id"] == speaker[0]
                            and row.get("draft_name") == speaker[1]
                        ):
                            self.speakers.update(index, draft_name=None)
                self._load_review(value, preserve_edits=True)
            finally:
                finish()

        self.background("qml-meeting-write", operation, receive, finish)

    @Slot(int)
    def saveSegment(self, index):
        if index in self._edits:
            edits = {index: self._edits[index]}
            session_id = self._review["id"]
            self._write(
                lambda: self.application.edit_meeting_segments(session_id, edits), edits
            )

    @Slot()
    def saveAll(self):
        if self._edits:
            edits = dict(self._edits)
            session_id = self._review["id"]
            self._write(
                lambda: self.application.edit_meeting_segments(session_id, edits), edits
            )

    @Slot()
    def discardEdits(self):
        if not self._writing:
            self._load_review(self._review)

    @Slot(int, str)
    def setSpeaker(self, index, speaker):
        session_id = self._review.get("id", "")
        self._write(
            lambda: self.application.set_meeting_segment_speaker(
                session_id, index, speaker
            )
        )

    @Slot(str, str)
    def renameSpeaker(self, speaker, name):
        session_id = self._review.get("id", "")
        self._write(
            lambda: self.application.set_meeting_speaker_name(
                session_id, speaker, name
            ),
            speaker=(speaker, name),
        )

    @Slot(int)
    def rerun(self, speakers):
        if self.dirty or self._writing:
            self.feedback.show("Salva le correzioni prima del ricalcolo")
            return
        self.attempt(
            lambda: self.application.rerun_meeting_diarization(
                self._review["id"], num_speakers=speakers
            )
        )

    @Slot(str)
    def export(self, fmt):
        if self.dirty or self._writing:
            self.feedback.show("Salva tutto prima di esportare")
            return
        self.attempt(lambda: export_session(self, self._review["id"], fmt))

    @Slot()
    def deleteAudio(self):
        session_id = self._review.get("id", "")
        self.background(
            "qml-audio-delete",
            lambda: self.application.delete_meeting_audio(session_id),
            lambda _: self.select(session_id),
        )

    def handle_event(self, name, value):
        if name in {"meeting_started", "meeting_updated"}:
            self.set_runtime(value)
        elif name == "meeting_queue_changed":
            self.queue.replace(value or [])
        elif name == "meeting_queue_job_updated":
            self.queue.upsert(value)
        elif name == "meeting_model_progress":
            self._model_progress = value or {}
            self.changed.emit()
        elif name == "meeting_review_changed" and not self.dirty and not self._writing:
            session_id = value.get("session_id") if isinstance(value, dict) else value
            if session_id == self._review.get("id"):
                self.select(session_id)
        elif name == "meeting_source_status":
            self.feedback.show("Sorgente riunione: " + str(value))
