"""Meeting input drafts and review, retaining edits through delegate recycling."""

import time
import uuid

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot

from ui.adapters.base import Adapter, choose_files, export_session
from ui.models import RecordModel

_QUALITY_NOTES = {
    "word_text_mismatch": "Tempi incompleti: il testo completo è stato conservato",
    "segment_text_mismatch": "Testo e tempi non coincidono: riascolta questo tratto",
    "degenerate_word_timing": "Tempi poco affidabili: verifica il cambio di voce",
    "invalid_word_timing": "Tempi poco affidabili: verifica il cambio di voce",
    "coarse_word_timing": "Verifica la voce ascoltando questo tratto",
    "nonmonotonic_word_timing": "Tempi poco affidabili: verifica il cambio di voce",
    "diarization_gap_bridged": "Voce attribuita per continuità: verifica ascoltando",
    "manual_layout_preserved": "Correzioni conservate durante il ricalcolo: verifica la voce",
    "approximate_recovered_timing": "Parole recuperate: tempi approssimativi, verifica audio e voce",
    "repetition_loop": "Ripetizione sospetta: riascolta questo tratto",
    "uncovered_audio": "Audio senza testo riconosciuto: riascolta questo tratto",
}


class MeetingAdapter(Adapter):
    changed = Signal()
    reviewChanged = Signal()
    draftChanged = Signal()
    dirtyChanged = Signal(bool)
    englishChanged = Signal()
    pipelineChanged = Signal()

    def __init__(self, application, feedback, parent=None):
        super().__init__(application, feedback, parent)
        self._default_language = "en"
        self._language_override = None
        self.start_guard = lambda: True
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
        self.pipelines = RecordModel([
            {"value": "qwen_meeting", "name": "Qwen · Riunioni"},
        ], self)
        self._pipeline = "qwen_meeting"
        self._english_status = {"ready": False, "busy": False, "progress": 0,
                                "dependencies_ready": False, "error": "", "download_gb": 0}
        self.queue = RecordModel(parent=self)
        self.segments = RecordModel(parent=self)
        self.speakers = RecordModel(parent=self)
        self.tracks = RecordModel(parent=self)
        self._runtime = {}
        self._review = {}
        self._review_summary = {}
        self._edits = {}
        self._audio = ""
        self._writing = False
        self._generation = 0
        self._runtime_clock = time.monotonic()
        self._model_progress = {}
        self._draft_owner = uuid.uuid4().hex
        self._draft_revision = 0
        self._draft_pending = False
        self._draft_writing = False
        self._draft_error = ""
        self._draft_conflicts = 0
        self._recovered_drafts_text = ""
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(250)
        self._draft_timer.timeout.connect(self._checkpoint_drafts)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.changed)
        self._timer.start()
        if hasattr(self.application, "english_pipeline_status"):
            QTimer.singleShot(0, self.refreshEnglish)

    @Property(str, notify=changed)
    def language(self):
        return self._default_language if self._language_override is None else self._language_override

    @Slot(str)
    def editLanguage(self, value):
        self._language_override = value
        self.changed.emit()

    @Slot()
    def resetLanguage(self):
        self._language_override = None
        self.changed.emit()

    def set_default_language(self, value):
        self._default_language = str(value)
        self.changed.emit()

    @Property(str, notify=pipelineChanged)
    def pipeline(self):
        return self._pipeline

    @Property("QVariantMap", notify=englishChanged)
    def englishStatus(self):
        return self._english_status

    def _english_status_received(self, value):
        if isinstance(value, dict):
            was_busy = bool(self._english_status.get("busy"))
            self._english_status = dict(value)
            self.pipelines.update(0, name="Qwen · Riunioni" if value.get("ready") else "Qwen · Riunioni (prepara modelli)")
            self.englishChanged.emit()
            if was_busy != bool(value.get("busy")):
                self.changed.emit()

    @Slot()
    def refreshEnglish(self):
        if hasattr(self.application, "english_pipeline_status"):
            self.background("qml-english-status", self.application.english_pipeline_status,
                            self._english_status_received)

    @Slot()
    def prepareEnglish(self):
        self._english_status = self._english_status | {"busy": True, "error": "", "progress": 0}
        self.englishChanged.emit()
        self.changed.emit()
        self.background("qml-english-models", self.application.prepare_english_models,
                        self._english_status_received, failed=self.refreshEnglish)

    @Slot()
    def cancelEnglish(self):
        self._english_status = self._english_status | {"cancelling": True}
        self.englishChanged.emit()
        self.background("qml-english-cancel", self.application.cancel_english_preparation,
                        self._english_status_received, failed=self.refreshEnglish)

    @Slot(str, result=bool)
    def selectPipeline(self, value):
        if value not in {"qwen_meeting"}:
            return False
        if value == "qwen_meeting" and not self._english_status.get("ready"):
            self.feedback.show("Prepara i modelli delle riunioni prima di avviare")
            return False
        self._pipeline = value
        self.pipelineChanged.emit()
        return True

    @Property("QVariantMap", notify=changed)
    def runtime(self):
        return self._runtime

    @Property("QVariantMap", notify=reviewChanged)
    def review(self):
        # The full document contains token timings and thousands of rows. Do
        # not serialize it into QML again on every keystroke or clock tick.
        return self._review_summary

    @Property("QVariantMap", notify=changed)
    def modelProgress(self):
        return self._model_progress

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._english_status.get("busy")) or bool(self._runtime) and self._runtime.get("status") not in {
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

    @Property(str, notify=draftChanged)
    def draftStatus(self):
        if self._draft_error:
            return "Bozza non protetta: usa Salva tutto"
        if self._draft_conflicts:
            return "Ci sono bozze recuperate da verificare"
        if self._draft_pending or self._draft_writing:
            return "Protezione della bozza in corso…"
        return (
            "Bozza protetta · conferma con Salva tutto"
            if self.dirty
            else "Tutte le modifiche salvate"
        )

    @Property(str, notify=draftChanged)
    def recoveredDraftsText(self):
        return self._recovered_drafts_text

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
                    {"path": p, "language": language, "num_speakers": speakers,
                     **({"pipeline": self._pipeline} if self._pipeline != "whisper" else {})}
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

    @Slot(int, str, "QVariant", result=bool)
    def editDraft(self, index, key, value):
        if key not in {"language", "num_speakers", "pipeline"}:
            return False
        if key == "pipeline" and value == "qwen_meeting" and not self._english_status.get("ready"):
            self.feedback.show("Prepara i modelli delle riunioni prima di avviare")
            return False
        if key == "pipeline" and value not in {"qwen_meeting"}:
            return False

        def edit():
            fields = {key: value}
            self.drafts.update(index, **fields)
            return True

        return self.attempt(edit) is True

    @Slot(int)
    def removeDraft(self, index):
        self.drafts.remove(index)

    @Slot(bool, str, int)
    def start(self, from_file, language, speakers):
        if not self.start_guard():
            return
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
                    **({"pipeline": self._pipeline} if self._pipeline != "whisper" else {}),
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
        if (self._draft_pending or self._draft_writing) and not self._flush_drafts():
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
                self._load_review(value[0] or {}, recover_drafts=True)

        self.background("qml-meeting-select", read, receive)

    def _load_review(self, value, preserve_edits=False, recover_drafts=False):
        same = value.get("id") == self._review.get("id")
        edits = dict(self._edits) if same and preserve_edits else {}
        self._review = value
        metadata = value.get("meeting") or {}
        if recover_drafts:
            edits = {
                int(index): text
                for index, text in (metadata.get("review_drafts") or {}).items()
            }
            self._draft_conflicts = len(metadata.get("draft_conflicts") or [])
            self._draft_error = metadata.get("draft_recovery_error", "")
            self._recovered_drafts_text = "\n\n".join(
                f"Intervento precedente {row['index'] + 1 if isinstance(row.get('index'), int) else '?'}\n"
                f"Testo di riferimento: {row.get('base_text', '')}\n"
                f"Bozza recuperata: {row.get('text', '')}"
                for row in metadata.get("draft_conflicts") or []
            )
            if self._draft_error:
                self.feedback.show(
                    "Non è stato possibile recuperare le bozze; il testo salvato è disponibile"
                )
            elif self._draft_conflicts:
                self.feedback.show(
                    "Alcune bozze si riferiscono a segmenti cambiati: sono conservate per il recupero"
                )
            elif edits:
                self.feedback.show("Recuperate le correzioni non ancora confermate")
        elif not same:
            self._draft_conflicts = 0
            self._recovered_drafts_text = ""
            self._draft_error = ""
        self._review_summary = {
            "id": value.get("id", ""),
            "started_at": value.get("started_at", ""),
            "text": value.get("text", ""),
            "full_text": value.get("full_text", ""),
            "meeting": {"num_speakers": metadata.get("num_speakers", 0)},
            "quality_notice": (
                "Ci sono tratti da riascoltare: gli avvisi di qualità sono conservati con la trascrizione"
                if any(
                    not issue.get("recovered")
                    for issue in value.get("quality_issues") or []
                )
                else ""
            ),
        }
        names = metadata.get("speaker_names") or {}
        ids = {key for key in names if key.startswith("SPEAKER_")}
        rows = []
        review_keys = metadata.get("review_keys") or []
        for index, item in enumerate(metadata.get("review_segments") or []):
            speaker = item.get("speaker_override") or item.get("speaker_id") or "UNKNOWN"
            if speaker.startswith("SPEAKER_"):
                ids.add(speaker)
            reasons = list(item.get("alignment_warnings") or [])
            reasons.extend(
                issue.get("reason") for issue in item.get("quality_issues") or []
            )
            quality_note = "; ".join(
                dict.fromkeys(
                    _QUALITY_NOTES[reason] for reason in reasons if reason in _QUALITY_NOTES
                )
            )
            rows.append(
                {
                    **item,
                    "index": index,
                    "review_key": review_keys[index] if index < len(review_keys) else "",
                    "speaker": speaker,
                    "speaker_name": names.get(
                        speaker, "Speaker ?" if speaker == "UNKNOWN" else speaker
                    ),
                    "speaker_choice": item.get("speaker_override") or "",
                    "overlap": len(item.get("overlap_speakers") or []) > 1,
                    "draft_text": edits.get(index, item.get("text", "")),
                    "dirty": index in edits,
                    "quality_note": quality_note,
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
        self.reviewChanged.emit()
        self.draftChanged.emit()
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
        self._queue_draft_checkpoint()
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
                        if row["id"] == speaker[0] and row.get("draft_name") == speaker[1]:
                            self.speakers.update(index, draft_name=None)
                self._load_review(value, preserve_edits=True)
                self._queue_draft_checkpoint()
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
            self._queue_draft_checkpoint()

    def _draft_snapshot(self):
        snapshot = {}
        for index, text in self._edits.items():
            row = self.segments.get(index)
            snapshot[index] = {
                "text": text,
                "base_text": row.get("text", ""),
                "review_key": row.get("review_key", ""),
            }
        return snapshot

    def _queue_draft_checkpoint(self):
        self._draft_revision += 1
        self._draft_pending = True
        if not self._draft_timer.isActive() and not self._draft_writing:
            self._draft_timer.start()
        self.draftChanged.emit()

    def _checkpoint_drafts(self):
        session_id = self._review.get("id")
        if not session_id or self._draft_writing or not self._draft_pending:
            return
        snapshot = self._draft_snapshot()
        revision = self._draft_revision
        self._draft_writing = True
        self._draft_pending = False
        self.draftChanged.emit()

        def finished():
            self._draft_writing = False
            if self._review.get("id") == session_id:
                self._draft_error = ""
            if self._draft_pending:
                self._draft_timer.start(0)
            self.draftChanged.emit()

        def failed():
            self._draft_writing = False
            if self._review.get("id") == session_id and revision == self._draft_revision:
                self._draft_pending = True
                self._draft_error = "checkpoint failed"
            elif self._draft_pending:
                self._draft_timer.start(0)
            self.draftChanged.emit()

        self.background(
            "qml-meeting-drafts",
            lambda: self.application.save_meeting_review_drafts(
                session_id, snapshot, self._draft_owner, revision
            ),
            lambda _: finished(),
            failed,
        )

    def _flush_drafts(self):
        """Finish the current small checkpoint before changing its owner view."""
        self._draft_timer.stop()
        if not self._review.get("id"):
            return True
        self._draft_revision += 1

        def write():
            self.application.save_meeting_review_drafts(
                self._review["id"],
                self._draft_snapshot(),
                self._draft_owner,
                self._draft_revision,
            )
            return True

        if not self.attempt(write):
            self._draft_error = "checkpoint failed"
            self.draftChanged.emit()
            return False
        self._draft_pending = False
        self._draft_error = ""
        self.draftChanged.emit()
        return True

    def close(self):
        if self._closed:
            return
        self._draft_timer.stop()
        self._timer.stop()
        if self._review.get("id") and (self._draft_pending or self._draft_writing):
            self._flush_drafts()
        super().close()

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
        elif name == "meeting_english_models_changed":
            self._english_status_received(value or {})
        elif name == "meeting_review_changed" and not self.dirty and not self._writing:
            session_id = value.get("session_id") if isinstance(value, dict) else value
            if session_id == self._review.get("id"):
                self.select(session_id)
        elif name == "meeting_source_status":
            self.feedback.show("Sorgente riunione: " + str(value))
        elif name == "meeting_quality_warning":
            self.feedback.show(
                "Un tratto è stato ritrascritto o richiede verifica; gli avvisi saranno disponibili nella revisione"
            )
