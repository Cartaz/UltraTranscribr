"""Meeting recording, final transcription, diarization and review lifecycle."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.event_bus import EventBus
from core.file_transcriber import FileTranscriberThread
from core.meeting_store import MeetingStore
from core.microphone_recording import MicrophoneRecorder, RecordingInfo
from core.sink_finder import find_source
from core.speaker_diarization import DiarizationModelManager, SpeakerDiarizer, align_speakers

logger = logging.getLogger(__name__)


class _RecordingOnlyBuffer:
    """AudioCaptureThread-compatible sink that discards Whisper chunks."""

    buffer_level = 0

    def put(self, _chunk) -> None:
        return

    def close_input(self) -> None:
        return

    def close(self) -> None:
        return


@dataclass
class MeetingRuntime:
    id: str
    microphone: str
    settings: Settings
    num_speakers: int
    recorder: MicrophoneRecorder
    capture: AudioCaptureThread
    status: str = "recording"
    progress: int = 0
    diarization_progress: int = 0
    transcriber: Optional[FileTranscriberThread] = None
    processing_thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    error: str = ""


class MeetingManager:
    """Own at most one active Meeting while keeping review data persistent."""

    def __init__(self, controller) -> None:
        self._controller = controller
        self.store = MeetingStore(controller.history)
        self.models = DiarizationModelManager()
        self.diarizer = SpeakerDiarizer(self.models)
        self._bus = EventBus()
        self._lock = threading.RLock()
        self._runtime: Optional[MeetingRuntime] = None
        # Recovering a multi-hour PCM journal can take noticeable time. Keep the
        # desktop startup path non-blocking; finalize orphaned journals on a
        # daemon worker and associate them with their persisted sessions later.
        self._recovery_thread = threading.Thread(
            target=self._recover_orphans,
            daemon=True,
            name="MeetingRecordingRecovery",
        )
        self._recovery_thread.start()

    def is_busy(self) -> bool:
        with self._lock:
            runtime = self._runtime
            return bool(runtime and runtime.status not in {"completed", "error", "cancelled", "interrupted"})

    def snapshot(self) -> Optional[dict[str, Any]]:
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return None
            return self._snapshot(runtime)

    def start(
        self,
        *,
        microphone: Optional[str] = None,
        language: Optional[str] = None,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        if self.is_busy():
            raise RuntimeError("Una riunione è già in corso")
        if self._controller.active_live_count() > 0 or self._controller.is_file_busy():
            raise RuntimeError("Ferma Live/File prima di avviare una riunione")
        settings = self._controller.settings.with_(
            audio_source=AudioSource.MICROPHONE.value,
            language=language or self._controller.settings.language,
            live_microphone_recording=False,
        )
        selected = str(microphone or "").strip()
        if not selected:
            selected = str(find_source(settings, audio_source=AudioSource.MICROPHONE.value) or "")
        if not selected:
            raise RuntimeError("Nessun microfono disponibile")
        session_id = self.store.create(
            model=settings.model_size,
            language=settings.language,
            microphone=selected,
            num_speakers=max(0, int(num_speakers)),
        )
        recorder = MicrophoneRecorder(session_id)
        recorder.start()
        capture = AudioCaptureThread(
            _RecordingOnlyBuffer(),
            settings,
            selected,
            AudioSource.MICROPHONE.value,
            session_id=f"meeting-{session_id}",
            event_sink=lambda event, payload: self._capture_event(session_id, event, payload),
            sample_sink=recorder.write,
        )
        runtime = MeetingRuntime(
            id=session_id,
            microphone=selected,
            settings=settings,
            num_speakers=max(0, int(num_speakers)),
            recorder=recorder,
            capture=capture,
        )
        with self._lock:
            self._runtime = runtime
        capture.start()
        self._emit("meeting_started", self._snapshot(runtime))
        self._emit("meeting_updated", self._snapshot(runtime))
        return self._snapshot(runtime)

    def finish(self) -> dict[str, Any]:
        runtime = self._require_runtime("recording")
        runtime.capture.stop()
        if runtime.capture.is_alive() and runtime.capture is not threading.current_thread():
            runtime.capture.join(timeout=8.0)
        if runtime.capture.is_alive():
            raise RuntimeError("Il microfono non si è arrestato in tempo; la registrazione resta aperta")
        info = self._finalize_recording(runtime)
        if info is None:
            self._fail(runtime, "Registrazione riunione vuota")
            return self._snapshot(runtime)
        runtime.status = "transcribing"
        runtime.progress = 0
        self.store.set_status(runtime.id, runtime.status)
        self._emit("meeting_recording_saved", {"session_id": runtime.id, **info.to_dict()})
        self._emit("meeting_updated", self._snapshot(runtime))
        worker = threading.Thread(
            target=self._process,
            args=(runtime, info),
            daemon=True,
            name=f"MeetingProcessing-{runtime.id}",
        )
        runtime.processing_thread = worker
        worker.start()
        return self._snapshot(runtime)

    def cancel(self) -> None:
        with self._lock:
            runtime = self._runtime
        if runtime is None or runtime.status in {"completed", "error", "cancelled", "interrupted"}:
            return
        runtime.stop_event.set()
        runtime.capture.stop()
        if runtime.capture.is_alive() and runtime.capture is not threading.current_thread():
            runtime.capture.join(timeout=5.0)
        transcriber = runtime.transcriber
        if transcriber is not None:
            transcriber.stop()
            if transcriber.is_alive():
                self._controller.backend.abort_active_request()
            if transcriber.is_alive() and transcriber is not threading.current_thread():
                transcriber.join(timeout=5.0)
        if runtime.status == "recording" and not runtime.capture.is_alive():
            try:
                self._finalize_recording(runtime)
            except Exception:
                logger.exception("Finalizzazione registrazione riunione annullata fallita")
                runtime.recorder.abandon()
        runtime.status = "cancelled"
        self.store.set_status(runtime.id, runtime.status, terminal=True)
        self._emit("meeting_updated", self._snapshot(runtime))
        self._emit("history_changed", runtime.id)

    def get(self, session_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(session_id)

    def set_speaker_name(self, session_id: str, speaker_id: str, name: str) -> dict[str, Any]:
        self.store.set_speaker_name(session_id, speaker_id, name)
        meeting = self.store.get(session_id)
        if meeting is None:
            raise KeyError("riunione non trovata")
        self._emit("meeting_review_changed", session_id)
        return meeting

    def edit_segment(self, session_id: str, index: int, text: str) -> dict[str, Any]:
        self.store.edit_review_segment(session_id, index, text)
        meeting = self.store.get(session_id)
        if meeting is None:
            raise KeyError("riunione non trovata")
        self._emit("meeting_review_changed", session_id)
        return meeting

    def delete_audio(self, session_id: str) -> bool:
        deleted = self.store.delete_audio(session_id)
        self._emit("meeting_review_changed", session_id)
        return deleted

    def prune_audio(self) -> int:
        return self.store.prune_audio(self._controller.settings.meeting_audio_retention_days)

    def shutdown(self) -> None:
        with self._lock:
            runtime = self._runtime
        if runtime is None:
            return
        runtime.stop_event.set()
        runtime.capture.stop()
        if runtime.capture.is_alive() and runtime.capture is not threading.current_thread():
            runtime.capture.join(timeout=5.0)
        transcriber = runtime.transcriber
        if transcriber is not None:
            transcriber.stop()
            if transcriber.is_alive():
                self._controller.backend.abort_active_request()
            if transcriber.is_alive() and transcriber is not threading.current_thread():
                transcriber.join(timeout=5.0)
        if runtime.status == "recording":
            try:
                if runtime.capture.is_alive():
                    runtime.recorder.abandon()
                else:
                    self._finalize_recording(runtime)
                runtime.status = "interrupted"
                self.store.set_status(runtime.id, "interrupted", terminal=True)
                self._emit("history_changed", runtime.id)
            except Exception:
                logger.exception("Shutdown registrazione Meeting fallito")
                runtime.recorder.abandon()
        processing = runtime.processing_thread
        if processing and processing.is_alive() and processing is not threading.current_thread():
            processing.join(timeout=2.0)

    def _process(self, runtime: MeetingRuntime, info: RecordingInfo) -> None:
        try:
            if runtime.stop_event.is_set():
                return
            self._controller.ensure_backend_started(vad=runtime.settings.vad_filter, settings=runtime.settings)
            if runtime.stop_event.is_set():
                return
            worker = FileTranscriberThread(
                info.path,
                self._controller.backend,
                runtime.settings,
                language=runtime.settings.language,
                event_sink=lambda event, payload: self._transcription_event(runtime, event, payload),
                thread_name=f"MeetingTranscriber-{runtime.id}",
            )
            runtime.transcriber = worker
            worker.start()
            worker.join()
            if runtime.stop_event.is_set() or runtime.status == "error":
                return
            history = self._controller.history.get_session(runtime.id)
            if not history:
                raise RuntimeError("trascrizione riunione non trovata")
            raw_segments = list(history.get("segments") or [])
            if not raw_segments:
                raise RuntimeError("Whisper non ha prodotto segmenti timestampati")

            runtime.status = "downloading_diarization" if not self.models.status()["ready"] else "diarizing"
            self.store.set_status(runtime.id, runtime.status)
            self._emit("meeting_updated", self._snapshot(runtime))
            self.models.ensure_models(
                lambda label, percent: self._model_progress(runtime, label, percent)
            )
            if runtime.stop_event.is_set():
                return
            runtime.status = "diarizing"
            runtime.diarization_progress = 0
            self.store.set_status(runtime.id, runtime.status)
            self._emit("meeting_updated", self._snapshot(runtime))
            diarization = self.diarizer.run(
                info.path,
                num_speakers=runtime.num_speakers if runtime.num_speakers > 0 else -1,
                progress=lambda percent: self._diarization_progress(runtime, percent),
            )
            if runtime.stop_event.is_set():
                return
            review = align_speakers(raw_segments, diarization)
            self.store.set_diarization(
                runtime.id,
                diarization_segments=diarization,
                review_segments=review,
            )
            runtime.status = "completed"
            runtime.progress = 100
            runtime.diarization_progress = 100
            self.store.set_status(runtime.id, runtime.status, terminal=True)
            self._emit("meeting_completed", runtime.id)
            self._emit("meeting_updated", self._snapshot(runtime))
            self._emit("history_changed", runtime.id)
            self.prune_audio()
        except Exception as exc:
            if runtime.stop_event.is_set():
                return
            logger.exception("Elaborazione riunione %s fallita", runtime.id)
            self._fail(runtime, str(exc))

    def _transcription_event(self, runtime: MeetingRuntime, event: str, payload: Any) -> None:
        if runtime.stop_event.is_set():
            return
        if event == "file_transcriber_new_text":
            text = str(payload or "").strip()
            if text:
                self._controller.history.append_text(runtime.id, text)
            return
        if event == "file_transcriber_segments":
            if isinstance(payload, list):
                self._controller.history.append_segments(runtime.id, payload)
            return
        if event == "file_transcriber_progress":
            runtime.progress = max(0, min(100, int(payload or 0)))
            self._emit("meeting_updated", self._snapshot(runtime))
            return
        if event == "file_transcriber_error":
            self._fail(runtime, str(payload or "Errore trascrizione riunione"))

    def _capture_event(self, session_id: str, event: str, payload: Any) -> None:
        if event != "transcriber_error":
            return
        with self._lock:
            runtime = self._runtime
        if runtime is not None and runtime.id == session_id:
            self._fail(runtime, str(payload or "Errore cattura microfono"))

    def _model_progress(self, runtime: MeetingRuntime, label: str, percent: int) -> None:
        if runtime.stop_event.is_set():
            return
        self._emit(
            "meeting_model_progress",
            {"session_id": runtime.id, "model": label, "percent": int(percent)},
        )

    def _diarization_progress(self, runtime: MeetingRuntime, percent: int) -> None:
        if runtime.stop_event.is_set():
            return
        runtime.diarization_progress = max(0, min(100, int(percent)))
        self._emit("meeting_updated", self._snapshot(runtime))

    def _fail(self, runtime: MeetingRuntime, error: str) -> None:
        if runtime.status == "recording":
            runtime.capture.stop()
            try:
                if runtime.capture is not threading.current_thread() and runtime.capture.is_alive():
                    runtime.capture.join(timeout=2.0)
                if not runtime.capture.is_alive():
                    self._finalize_recording(runtime)
                else:
                    runtime.recorder.abandon()
            except Exception:
                logger.exception("Salvataggio audio dopo errore Meeting fallito")
                runtime.recorder.abandon()
        runtime.error = str(error)
        runtime.status = "error"
        try:
            self.store.set_status(runtime.id, "error", terminal=True)
        except Exception:
            logger.exception("Persistenza errore Meeting fallita")
        self._emit("meeting_error", {"session_id": runtime.id, "error": runtime.error})
        self._emit("meeting_updated", self._snapshot(runtime))
        self._emit("history_changed", runtime.id)

    def _finalize_recording(self, runtime: MeetingRuntime) -> Optional[RecordingInfo]:
        info = runtime.recorder.finalize()
        if info is not None:
            self.store.set_recording(runtime.id, info.to_dict())
        return info

    def _require_runtime(self, status: str) -> MeetingRuntime:
        with self._lock:
            runtime = self._runtime
        if runtime is None or runtime.status != status:
            raise RuntimeError("Nessuna riunione in registrazione")
        return runtime

    @staticmethod
    def _snapshot(runtime: MeetingRuntime) -> dict[str, Any]:
        return {
            "id": runtime.id,
            "status": runtime.status,
            "microphone": runtime.microphone,
            "language": runtime.settings.language,
            "model": runtime.settings.model_size,
            "num_speakers": runtime.num_speakers,
            "duration_s": round(runtime.recorder.duration_s, 1),
            "progress": runtime.progress,
            "diarization_progress": runtime.diarization_progress,
            "error": runtime.error,
        }

    def _recover_orphans(self) -> None:
        for info in MicrophoneRecorder.recover_orphaned():
            session_id = Path(info.path).stem
            meeting = self.store.get(session_id)
            if meeting is None:
                # Live microphone recordings are recovered by the same shared
                # recorder and remain discoverable by session ID in History.
                continue
            try:
                self.store.set_recording(session_id, info.to_dict())
                self.store.set_status(session_id, "interrupted", terminal=True)
                self._emit("meeting_recording_saved", {"session_id": session_id, **info.to_dict()})
                self._emit("history_changed", session_id)
            except Exception:
                logger.exception("Associazione recovery Meeting fallita: %s", session_id)

    def _emit(self, event: str, payload: Any = None) -> None:
        self._bus.emit(event, payload)
