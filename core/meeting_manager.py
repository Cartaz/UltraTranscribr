"""Meeting acquisition, final transcription, diarization and review lifecycle."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from config.constants import AppMeta
from config.settings import AudioSource, Settings
from core.audio_inputs import AudioInputResolver, AudioInputSelection
from core.event_bus import EventBus
from core.file_transcriber import FileTranscriberThread
from core.meeting_capture import (
    MeetingCaptureSession,
    MeetingRecordingBundle,
    mix_recordings,
    normalize_media_to_flac,
)
from core.meeting_store import MeetingStore
from core.microphone_recording import MicrophoneRecorder, RecordingInfo
from core.speaker_diarization import DiarizationModelManager, SpeakerDiarizer, align_speakers
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)


class MeetingController(Protocol):
    """Small application contract required by MeetingManager."""

    @property
    def settings(self) -> Settings: ...

    @property
    def history(self) -> TranscriptHistoryStore: ...

    @property
    def backend(self) -> WhisperBackend: ...

    def active_live_count(self) -> int: ...

    def is_file_busy(self) -> bool: ...

    def ensure_backend_started(
        self,
        *,
        vad: Optional[bool] = None,
        settings: Optional[Settings] = None,
    ) -> None: ...


@dataclass
class MeetingRuntime:
    id: str
    mode: str
    settings: Settings
    num_speakers: int
    sources: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""
    capture: Optional[MeetingCaptureSession] = None
    recording: Optional[RecordingInfo] = None
    status: str = "recording"
    progress: int = 0
    diarization_progress: int = 0
    transcriber: Optional[FileTranscriberThread] = None
    preparation_thread: Optional[threading.Thread] = None
    processing_thread: Optional[threading.Thread] = None
    control_thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    error: str = ""


class MeetingManager:
    """Own one Meeting workflow while acquisition remains replaceable."""

    _TERMINAL_STATUSES = {"completed", "error", "cancelled", "interrupted"}
    _MAX_REALTIME_SOURCES = 8
    _RECOVERY_JOIN_TIMEOUT_S = 5.0
    _CONTROL_JOIN_TIMEOUT_S = 10.0
    _TRANSCRIBER_JOIN_TIMEOUT_S = 5.0
    _PROCESSING_JOIN_TIMEOUT_S = 5.0
    _PREPARATION_JOIN_TIMEOUT_S = 5.0

    def __init__(
        self,
        controller: MeetingController,
        input_resolver: AudioInputResolver,
    ) -> None:
        self._controller = controller
        self._inputs = input_resolver
        self.store = MeetingStore(controller.history)
        self.models = DiarizationModelManager()
        self.diarizer = SpeakerDiarizer(self.models)
        self._bus = EventBus()
        self._lock = threading.RLock()
        self._runtime: Optional[MeetingRuntime] = None
        self._closed = False
        self._shutdown_event = threading.Event()
        self._recovery_thread = threading.Thread(
            target=self._recover_orphans,
            daemon=True,
            name="MeetingRecordingRecovery",
        )
        self._recovery_thread.start()

    def is_busy(self) -> bool:
        with self._lock:
            runtime = self._runtime
            return bool(runtime and runtime.status not in self._TERMINAL_STATUSES)

    def snapshot(self) -> Optional[dict[str, Any]]:
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return None
            return self._snapshot(runtime)

    def start_realtime(
        self,
        sources: list[AudioInputSelection | dict[str, Any]],
        *,
        language: Optional[str] = None,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        self._require_start_available()
        selections = self._normalize_sources(sources)
        settings = self._controller.settings.with_(
            language=language or self._controller.settings.language,
            live_microphone_recording=False,
        )
        source_name = selections[0].source if len(selections) == 1 else "multisource"
        source_path = "; ".join(self._selection_label(item) for item in selections)
        session_id = self.store.create(
            model=settings.model_size,
            language=settings.language,
            source=source_name,
            source_path=source_path,
            acquisition_mode="realtime",
            num_speakers=max(0, int(num_speakers)),
        )
        planned_sources = [
            {
                "id": f"source-{index + 1}",
                **selection.to_dict(),
                "recording": {},
            }
            for index, selection in enumerate(selections)
        ]
        self.store.set_source_recordings(session_id, planned_sources)
        capture = MeetingCaptureSession(
            session_id,
            settings,
            self._inputs,
            event_sink=lambda event, payload: self._capture_event(session_id, event, payload),
        )
        runtime = MeetingRuntime(
            id=session_id,
            mode="realtime",
            settings=settings,
            num_speakers=max(0, int(num_speakers)),
            sources=planned_sources,
            source_path=source_path,
            capture=capture,
            status="recording",
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("gestore Meeting chiuso")
            self._runtime = runtime
        try:
            capture.start(selections)
        except Exception as exc:
            logger.exception("Avvio acquisizione Meeting fallito")
            self._fail(runtime, str(exc))
            raise RuntimeError(str(exc)) from exc
        self._emit("meeting_started", self._snapshot(runtime))
        self._emit("meeting_updated", self._snapshot(runtime))
        return self._snapshot(runtime)

    def start_file(
        self,
        file_path: Path | str,
        *,
        language: Optional[str] = None,
        num_speakers: int = 0,
    ) -> dict[str, Any]:
        self._require_start_available()
        source = Path(file_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError("Seleziona una registrazione esistente")
        settings = self._controller.settings.with_(
            language=language or self._controller.settings.language,
            live_microphone_recording=False,
        )
        session_id = self.store.create(
            model=settings.model_size,
            language=settings.language,
            source="file",
            source_path=str(source),
            acquisition_mode="file",
            num_speakers=max(0, int(num_speakers)),
        )
        planned = [
            {
                "id": "source-1",
                "source": "file",
                "source_path": str(source),
                "label": source.name,
                "recording": {},
            }
        ]
        self.store.set_source_recordings(session_id, planned)
        runtime = MeetingRuntime(
            id=session_id,
            mode="file",
            settings=settings,
            num_speakers=max(0, int(num_speakers)),
            sources=planned,
            source_path=str(source),
            status="preparing_file",
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("gestore Meeting chiuso")
            self._runtime = runtime
        worker = threading.Thread(
            target=self._prepare_file,
            args=(runtime, source),
            daemon=True,
            name=f"MeetingFilePrepare-{session_id}",
        )
        runtime.preparation_thread = worker
        self._emit("meeting_started", self._snapshot(runtime))
        self._emit("meeting_updated", self._snapshot(runtime))
        worker.start()
        return self._snapshot(runtime)

    def finish(self) -> dict[str, Any]:
        """Request finalization without blocking the caller on audio shutdown."""
        runtime = self._require_runtime("recording")
        if runtime.mode != "realtime" or runtime.capture is None:
            raise RuntimeError("La riunione corrente non è un'acquisizione realtime")
        with self._lock:
            if self._closed:
                raise RuntimeError("gestore Meeting chiuso")
            control = runtime.control_thread
            if control is not None and control.is_alive():
                return self._snapshot(runtime)
            runtime.status = "finishing"
            runtime.error = ""
            self.store.set_status(runtime.id, runtime.status)
            control = threading.Thread(
                target=self._finish_realtime,
                args=(runtime,),
                daemon=True,
                name=f"MeetingFinalize-{runtime.id}",
            )
            runtime.control_thread = control
            snapshot = self._snapshot(runtime)
        self._emit("meeting_updated", snapshot)
        control.start()
        return snapshot

    def _finish_realtime(self, runtime: MeetingRuntime) -> None:
        try:
            assert runtime.capture is not None
            bundle = runtime.capture.stop_and_finalize()
            self._store_bundle(runtime, bundle)
            self._emit(
                "meeting_recording_saved",
                {"session_id": runtime.id, **bundle.recording.to_dict()},
            )
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
                runtime.status = "interrupted"
                self.store.set_status(runtime.id, runtime.status, terminal=True)
                self._emit("meeting_updated", self._snapshot(runtime))
                self._emit("history_changed", runtime.id)
                return
            self._begin_analysis(runtime, bundle.recording)
        except Exception as exc:
            logger.exception("Finalizzazione registrazione Meeting fallita")
            self._fail(runtime, str(exc))
        finally:
            with self._lock:
                if runtime.control_thread is threading.current_thread():
                    runtime.control_thread = None

    def _prepare_file(self, runtime: MeetingRuntime, source: Path) -> None:
        try:
            info = normalize_media_to_flac(
                source,
                AppMeta.RECORDINGS_DIR / f"{runtime.id}.flac",
                stop_event=runtime.stop_event,
            )
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
                return
            runtime.recording = info
            runtime.sources = [
                {
                    "id": "source-1",
                    "source": "file",
                    "source_path": str(source),
                    "label": source.name,
                    "offset_s": 0.0,
                    "recording": info.to_dict(),
                }
            ]
            self.store.set_recording(runtime.id, info.to_dict())
            self.store.set_source_recordings(runtime.id, runtime.sources)
            self._emit(
                "meeting_recording_saved",
                {"session_id": runtime.id, **info.to_dict()},
            )
            self._begin_analysis(runtime, info)
        except Exception as exc:
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
                return
            logger.exception("Preparazione file Meeting fallita")
            self._fail(runtime, str(exc))
        finally:
            with self._lock:
                if runtime.preparation_thread is threading.current_thread():
                    runtime.preparation_thread = None

    def _begin_analysis(self, runtime: MeetingRuntime, info: RecordingInfo) -> None:
        if runtime.stop_event.is_set() or self._shutdown_event.is_set():
            return
        runtime.recording = info
        runtime.status = "transcribing"
        runtime.progress = 0
        self.store.set_status(runtime.id, runtime.status)
        self._emit("meeting_updated", self._snapshot(runtime))
        worker = threading.Thread(
            target=self._process,
            args=(runtime, info),
            daemon=True,
            name=f"MeetingProcessing-{runtime.id}",
        )
        runtime.processing_thread = worker
        worker.start()

    def cancel(self) -> None:
        """Request cancellation without blocking the caller on worker joins."""
        with self._lock:
            if self._closed:
                return
            runtime = self._runtime
            if runtime is None or runtime.status in self._TERMINAL_STATUSES:
                return
            control = runtime.control_thread
            if control is not None and control.is_alive():
                return
            previous_status = runtime.status
            runtime.stop_event.set()
            runtime.status = "cancelling"
            runtime.error = ""
            self.store.set_status(runtime.id, runtime.status)
            control = threading.Thread(
                target=self._cancel_runtime,
                args=(runtime, previous_status),
                daemon=True,
                name=f"MeetingCancel-{runtime.id}",
            )
            runtime.control_thread = control
            snapshot = self._snapshot(runtime)
        self._emit("meeting_updated", snapshot)
        control.start()

    def _cancel_runtime(self, runtime: MeetingRuntime, previous_status: str) -> None:
        try:
            if runtime.capture is not None and previous_status in {"recording", "finishing"}:
                try:
                    bundle = runtime.capture.stop_and_finalize()
                    self._store_bundle(runtime, bundle)
                except Exception:
                    logger.exception("Finalizzazione acquisizione Meeting annullata fallita")
                    runtime.capture.abandon()

            transcriber = runtime.transcriber
            if transcriber is not None:
                transcriber.stop()
                if transcriber.is_alive():
                    self._controller.backend.abort_active_request()
                if transcriber.is_alive() and transcriber is not threading.current_thread():
                    transcriber.join(timeout=self._TRANSCRIBER_JOIN_TIMEOUT_S)

            preparation = runtime.preparation_thread
            if preparation and preparation.is_alive() and preparation is not threading.current_thread():
                preparation.join(timeout=self._PREPARATION_JOIN_TIMEOUT_S)
                if preparation.is_alive():
                    logger.warning("Preparazione Meeting %s ancora attiva dopo cancel", runtime.id)

            runtime.status = "cancelled"
            self.store.set_status(runtime.id, runtime.status, terminal=True)
            self._emit("meeting_updated", self._snapshot(runtime))
            self._emit("history_changed", runtime.id)
        except Exception as exc:
            logger.exception("Annullamento Meeting fallito")
            self._fail(runtime, str(exc))
        finally:
            with self._lock:
                if runtime.control_thread is threading.current_thread():
                    runtime.control_thread = None

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
            if self._closed:
                return
            self._closed = True
            runtime = self._runtime
        self._shutdown_event.set()
        current = threading.current_thread()

        recovery = self._recovery_thread
        if recovery.is_alive() and recovery is not current:
            recovery.join(timeout=self._RECOVERY_JOIN_TIMEOUT_S)
            if recovery.is_alive():
                logger.warning("MeetingRecordingRecovery ancora attivo dopo shutdown bounded")

        if runtime is None:
            return
        runtime.stop_event.set()

        control = runtime.control_thread
        if control and control.is_alive() and control is not current:
            control.join(timeout=self._CONTROL_JOIN_TIMEOUT_S)
            if control.is_alive():
                logger.warning("Control Meeting %s ancora attivo dopo shutdown bounded", runtime.id)

        if runtime.capture is not None and runtime.status in {"recording", "finishing", "cancelling"}:
            try:
                bundle = runtime.capture.stop_and_finalize()
                self._store_bundle(runtime, bundle)
                runtime.status = "interrupted"
                self.store.set_status(runtime.id, "interrupted", terminal=True)
                self._emit("history_changed", runtime.id)
            except Exception:
                logger.exception("Shutdown acquisizione Meeting fallito")
                runtime.capture.abandon()

        transcriber = runtime.transcriber
        if transcriber is not None:
            transcriber.stop()
            if transcriber.is_alive():
                self._controller.backend.abort_active_request()
            if transcriber.is_alive() and transcriber is not current:
                transcriber.join(timeout=self._TRANSCRIBER_JOIN_TIMEOUT_S)
                if transcriber.is_alive():
                    logger.warning("Transcriber Meeting %s ancora attivo dopo shutdown bounded", runtime.id)

        preparation = runtime.preparation_thread
        if preparation and preparation.is_alive() and preparation is not current:
            preparation.join(timeout=self._PREPARATION_JOIN_TIMEOUT_S)
            if preparation.is_alive():
                logger.warning("Preparazione Meeting %s ancora attiva dopo shutdown bounded", runtime.id)

        processing = runtime.processing_thread
        if processing and processing.is_alive() and processing is not current:
            processing.join(timeout=self._PROCESSING_JOIN_TIMEOUT_S)
            if processing.is_alive():
                logger.warning("Processing Meeting %s ancora attivo dopo shutdown bounded", runtime.id)

        if runtime.status not in self._TERMINAL_STATUSES:
            runtime.status = "interrupted"
            self.store.set_status(runtime.id, "interrupted", terminal=True)
            self._emit("meeting_updated", self._snapshot(runtime))
            self._emit("history_changed", runtime.id)

    def _process(self, runtime: MeetingRuntime, info: RecordingInfo) -> None:
        try:
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
                return
            self._controller.ensure_backend_started(
                vad=runtime.settings.vad_filter,
                settings=runtime.settings,
            )
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
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
            if runtime.stop_event.is_set() or self._shutdown_event.is_set() or runtime.status == "error":
                return
            history = self._controller.history.get_session(runtime.id)
            if not history:
                raise RuntimeError("trascrizione riunione non trovata")
            raw_segments = list(history.get("segments") or [])
            if not raw_segments:
                raise RuntimeError("Whisper non ha prodotto segmenti timestampati")

            runtime.status = (
                "downloading_diarization"
                if not self.models.status()["ready"]
                else "diarizing"
            )
            self.store.set_status(runtime.id, runtime.status)
            self._emit("meeting_updated", self._snapshot(runtime))
            self.models.ensure_models(
                lambda label, percent: self._model_progress(runtime, label, percent)
            )
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
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
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
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
            if runtime.stop_event.is_set() or self._shutdown_event.is_set():
                return
            logger.exception("Elaborazione riunione %s fallita", runtime.id)
            self._fail(runtime, str(exc))

    def _transcription_event(self, runtime: MeetingRuntime, event: str, payload: Any) -> None:
        if runtime.stop_event.is_set() or self._shutdown_event.is_set():
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
        if event not in {"transcriber_error", "route_status"}:
            return
        with self._lock:
            runtime = self._runtime
        if runtime is None or runtime.id != session_id:
            return
        if event == "route_status":
            self._emit(
                "meeting_source_status",
                {"session_id": session_id, **dict(payload or {})},
            )
            return
        detail = payload.get("payload") if isinstance(payload, dict) else payload
        self._fail(runtime, str(detail or "Errore cattura sorgente riunione"))

    def _model_progress(self, runtime: MeetingRuntime, label: str, percent: int) -> None:
        if runtime.stop_event.is_set() or self._shutdown_event.is_set():
            return
        self._emit(
            "meeting_model_progress",
            {"session_id": runtime.id, "model": label, "percent": int(percent)},
        )

    def _diarization_progress(self, runtime: MeetingRuntime, percent: int) -> None:
        if runtime.stop_event.is_set() or self._shutdown_event.is_set():
            return
        runtime.diarization_progress = max(0, min(100, int(percent)))
        self._emit("meeting_updated", self._snapshot(runtime))

    def _fail(self, runtime: MeetingRuntime, error: str) -> None:
        if runtime.status in self._TERMINAL_STATUSES:
            return
        if runtime.capture is not None and runtime.status in {"recording", "finishing", "cancelling"}:
            try:
                bundle = runtime.capture.stop_and_finalize()
                self._store_bundle(runtime, bundle)
            except Exception:
                logger.exception("Salvataggio audio dopo errore Meeting fallito")
                runtime.capture.abandon()
        runtime.error = str(error)
        runtime.status = "error"
        try:
            self.store.set_status(runtime.id, "error", terminal=True)
        except Exception:
            logger.exception("Persistenza errore Meeting fallita")
        self._emit("meeting_error", {"session_id": runtime.id, "error": runtime.error})
        self._emit("meeting_updated", self._snapshot(runtime))
        self._emit("history_changed", runtime.id)

    def _store_bundle(
        self,
        runtime: MeetingRuntime,
        bundle: MeetingRecordingBundle,
    ) -> None:
        runtime.recording = bundle.recording
        runtime.sources = list(bundle.sources)
        self.store.set_recording(runtime.id, bundle.recording.to_dict())
        self.store.set_source_recordings(runtime.id, bundle.sources)

    def _require_start_available(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("gestore Meeting chiuso")
        if self.is_busy():
            raise RuntimeError("Una riunione è già in corso")
        if self._controller.active_live_count() > 0 or self._controller.is_file_busy():
            raise RuntimeError("Ferma Live/File prima di avviare una riunione")

    def _require_runtime(self, status: str) -> MeetingRuntime:
        with self._lock:
            runtime = self._runtime
        if runtime is None or runtime.status != status:
            raise RuntimeError("Nessuna riunione in registrazione")
        return runtime

    def _normalize_sources(
        self,
        values: list[AudioInputSelection | dict[str, Any]],
    ) -> list[AudioInputSelection]:
        if not isinstance(values, list) or not values:
            raise ValueError("Aggiungi almeno una sorgente alla riunione")
        if len(values) > self._MAX_REALTIME_SOURCES:
            raise ValueError(
                f"Una riunione supporta al massimo {self._MAX_REALTIME_SOURCES} sorgenti"
            )
        selections = [
            value if isinstance(value, AudioInputSelection) else AudioInputSelection.from_mapping(value)
            for value in values
        ]
        keys: set[tuple[str, str, Optional[int]]] = set()
        for selection in selections:
            key = (selection.source, selection.selected_input, selection.stream_id)
            if key in keys:
                raise ValueError("La stessa sorgente non può essere aggiunta due volte")
            keys.add(key)
        return selections

    @staticmethod
    def _selection_label(selection: AudioInputSelection) -> str:
        if selection.label:
            return selection.label
        if selection.source == AudioSource.APPLICATION.value:
            return f"application:{selection.stream_id}"
        return selection.selected_input or selection.source

    @staticmethod
    def _snapshot(runtime: MeetingRuntime) -> dict[str, Any]:
        duration = runtime.recording.duration_s if runtime.recording is not None else 0.0
        if runtime.capture is not None and runtime.status in {"recording", "finishing"}:
            duration = runtime.capture.duration_s
        return {
            "id": runtime.id,
            "mode": runtime.mode,
            "status": runtime.status,
            "sources": [dict(item) for item in runtime.sources],
            "source_path": runtime.source_path,
            "language": runtime.settings.language,
            "model": runtime.settings.model_size,
            "num_speakers": runtime.num_speakers,
            "duration_s": round(duration, 1),
            "progress": runtime.progress,
            "diarization_progress": runtime.diarization_progress,
            "error": runtime.error,
        }

    def _recover_orphans(self) -> None:
        grouped: dict[str, list[RecordingInfo]] = {}
        for info in MicrophoneRecorder.recover_orphaned():
            if self._shutdown_event.is_set():
                return
            stem = Path(info.path).stem
            session_id = stem.split("-source-", 1)[0] if "-source-" in stem else stem
            if self.store.get(session_id) is not None:
                grouped.setdefault(session_id, []).append(info)

        for session_id, infos in grouped.items():
            if self._shutdown_event.is_set():
                return
            try:
                direct = next(
                    (info for info in infos if Path(info.path).stem == session_id),
                    None,
                )
                if direct is not None:
                    canonical = direct
                else:
                    canonical = mix_recordings(
                        [(info, 0.0) for info in infos],
                        AppMeta.RECORDINGS_DIR / f"{session_id}.flac",
                    )
                meeting = self.store.get(session_id) or {}
                planned = list(
                    (meeting.get("meeting") or {})
                    .get("acquisition", {})
                    .get("sources")
                    or []
                )
                source_records: list[dict[str, Any]] = []
                for index, info in enumerate(infos):
                    base = (
                        dict(planned[index])
                        if index < len(planned)
                        else {
                            "id": f"source-{index + 1}",
                            "source": "recovered",
                            "label": f"Recovered {index + 1}",
                        }
                    )
                    base["offset_s"] = 0.0
                    base["recording"] = info.to_dict()
                    source_records.append(base)
                self.store.set_recording(session_id, canonical.to_dict())
                self.store.set_source_recordings(session_id, source_records)
                self.store.set_status(session_id, "interrupted", terminal=True)
                self._emit(
                    "meeting_recording_saved",
                    {"session_id": session_id, **canonical.to_dict()},
                )
                self._emit("history_changed", session_id)
            except Exception:
                logger.exception("Associazione recovery Meeting fallita: %s", session_id)

    def _emit(self, event: str, payload: Any = None) -> None:
        self._bus.emit(event, payload)
