"""Application controller coordinating live sessions, files and shared backend."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from config.settings import AudioSource, Settings
from core.audio_routing import PulseAudioRouter
from core.event_bus import EventBus
from core.exceptions import GPUNotAvailableError, SinkNotFoundError
from core.file_batch import FileBatchCoordinator
from core.file_transcriber import FileTranscriberThread
from core.live_sessions import LiveSessionManager
from core.meeting_manager import MeetingManager
from core.models import StatusEnum
from core.sink_finder import find_source
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend
from core.whisper_gpu_detect import detect_gpu_backend
from core.whisper_models import WhisperModelManager

logger = logging.getLogger(__name__)


class _AggregateLiveBufferView:
    """Compatibility/read-only view over all live session buffers."""

    def __init__(self, sessions: LiveSessionManager) -> None:
        self._sessions = sessions

    @property
    def buffer_level(self) -> int:
        snapshots = self._sessions.list_sessions()
        return max((int(item.get("buffer_level", 0)) for item in snapshots), default=0)


class _MeetingControllerView:
    """Narrow application facade consumed by MeetingManager."""

    def __init__(self, controller: "AppController") -> None:
        self._controller = controller

    @property
    def settings(self) -> Settings:
        return self._controller.settings

    @property
    def history(self) -> TranscriptHistoryStore:
        return self._controller.history

    @property
    def backend(self) -> WhisperBackend:
        return self._controller.backend

    def active_live_count(self) -> int:
        return self._controller.active_live_count()

    def is_file_busy(self) -> bool:
        return self._controller.is_file_busy()

    def ensure_backend_started(
        self,
        *,
        vad: Optional[bool] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._controller.ensure_backend_started(vad=vad, settings=settings)


class AppController:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._project_root = Path(__file__).resolve().parent.parent
        self._bus = EventBus()
        if detect_gpu_backend(self._project_root) != "sycl":
            raise GPUNotAvailableError(
                "Backend SYCL non disponibile su questo sistema",
                detail="Verificare Intel oneAPI, Level Zero e Intel Compute Runtime.",
            )

        self._model_manager = WhisperModelManager()
        self._backend = WhisperBackend(settings, self._project_root)
        self._history = TranscriptHistoryStore()
        self._audio_router = PulseAudioRouter()
        try:
            self._audio_router.cleanup_stale_routes()
        except Exception as exc:
            logger.warning("Cleanup routing audio precedente fallito: %s", exc)

        self._lock = threading.RLock()
        self._backend_init_lock = threading.Lock()
        self._model_operation_lock = threading.Lock()
        self._generation = 0
        self._file_thread: Optional[FileTranscriberThread] = None
        self._startup_thread: Optional[threading.Thread] = None
        self._backend_started = False
        self._file_history_id: Optional[str] = None
        self._history_subscriptions: list[tuple[str, Callable[[Any], None]]] = []

        self._live_sessions = LiveSessionManager(
            backend=self._backend,
            router=self._audio_router,
            history=self._history,
            backend_initializer=self._ensure_backend_for_live_session,
            sink_resolver=self._resolve_sink,
        )
        self._buffer_view = _AggregateLiveBufferView(self._live_sessions)
        self._meeting = MeetingManager(_MeetingControllerView(self))
        self._file_batch = FileBatchCoordinator(self)
        self._subscribe_history_events()

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def buffer(self) -> _AggregateLiveBufferView:
        return self._buffer_view

    @property
    def backend(self) -> WhisperBackend:
        return self._backend

    @property
    def history(self) -> TranscriptHistoryStore:
        return self._history

    @property
    def live_sessions(self) -> LiveSessionManager:
        return self._live_sessions

    @property
    def meeting(self) -> MeetingManager:
        return self._meeting

    @property
    def file_batch(self) -> FileBatchCoordinator:
        return self._file_batch

    def _next_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def ensure_backend_started(
        self,
        *,
        vad: Optional[bool] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or self._settings
        wanted = cfg.vad_filter if vad is None else bool(vad)
        with self._backend_init_lock:
            with self._lock:
                already = self._backend_started and self._backend.is_running

            vad_path = None
            if wanted:
                self._bus.emit("backend_status_changed", "preparing_vad")
                vad_path = self._model_manager.get_vad_model_path()

            if already:
                self._bus.emit("backend_status_changed", "configuring_backend")
                self._backend.ensure_vad_mode(wanted, vad_path)
                self._bus.emit("backend_status_changed", "ready")
                return

            info = self._model_manager.get_model_info(cfg.model_size)
            if not bool(info.get("installed")):
                self._bus.emit("backend_status_changed", "downloading_model")
                self._bus.emit("model_download_started", {"model": cfg.model_size})

                def progress(downloaded: int, total: Optional[int]) -> None:
                    percent = None
                    if total and total > 0:
                        percent = min(100, int(downloaded * 100 / total))
                    self._bus.emit(
                        "model_download_progress",
                        {
                            "model": cfg.model_size,
                            "downloaded": downloaded,
                            "total": total,
                            "percent": percent,
                        },
                    )

                model = self._model_manager.download_model(cfg.model_size, progress)
                self._bus.emit(
                    "model_status_changed",
                    {"model": cfg.model_size, "action": "downloaded"},
                )
            else:
                self._bus.emit(
                    "backend_status_changed",
                    StatusEnum.LOADING_MODEL.value,
                )
                model = self._model_manager.get_model_path(cfg.model_size)

            self._bus.emit("backend_status_changed", "starting_backend")
            self._backend.start(model, vad_path)
            self._backend.ensure_vad_mode(wanted, vad_path)
            with self._lock:
                self._backend_started = True
            self._bus.emit("backend_status_changed", "ready")

    def _ensure_backend_for_live_session(self, settings: Settings) -> None:
        self.ensure_backend_started(vad=settings.vad_filter, settings=settings)

    def stop_backend(self) -> None:
        # Startup and shutdown share the same lifecycle lock. This prevents a
        # stop from racing a half-started whisper-server and also guarantees
        # that shutdown wins once an in-flight startup leaves the critical
        # section.
        with self._backend_init_lock:
            with self._lock:
                self._backend.stop()
                self._backend_started = False
        self._bus.emit("backend_status_changed", "standby")

    def _run_async(
        self,
        generation: int,
        target: Callable[[], None],
        error_event: str,
    ) -> None:
        def wrapped() -> None:
            try:
                target()
            except Exception as exc:
                logger.exception("Avvio asincrono fallito")
                if self._is_current(generation):
                    self._bus.emit("backend_status_changed", StatusEnum.ERROR.value)
                    self._bus.emit(error_event, str(exc))
                    self._bus.emit(
                        "file_transcriber_status_changed",
                        StatusEnum.ERROR.value,
                    )
            finally:
                with self._lock:
                    if self._startup_thread is threading.current_thread():
                        self._startup_thread = None

        thread = threading.Thread(
            target=wrapped,
            daemon=True,
            name="ControllerStartup",
        )
        with self._lock:
            self._startup_thread = thread
        thread.start()

    # ------------------------------------------------------------------
    # Live sessions
    # ------------------------------------------------------------------
    def start_live_session(
        self,
        *,
        sink_name: Optional[str] = None,
        audio_source: Optional[str] = None,
        language: Optional[str] = None,
        stream_id: Optional[int] = None,
        record_audio: bool = False,
    ) -> dict[str, Any]:
        if self.is_file_busy():
            raise RuntimeError(
                "Ferma la trascrizione file prima di avviare una sessione Live"
            )
        source = audio_source or self._settings.audio_source
        session_settings = self._settings.with_(
            live_microphone_recording=bool(
                record_audio and source == AudioSource.MICROPHONE.value
            )
        )
        return self._live_sessions.create_session(
            settings=session_settings,
            audio_source=source,
            sink_name=sink_name,
            language=language,
            stream_id=stream_id,
        )

    def list_live_sessions(self, *, include_text: bool = False) -> list[dict[str, Any]]:
        return self._live_sessions.list_sessions(include_text=include_text)

    def get_live_session(
        self,
        session_id: str,
        *,
        include_text: bool = False,
    ) -> Optional[dict[str, Any]]:
        return self._live_sessions.get_session(session_id, include_text=include_text)

    def stop_live_session(self, session_id: str, *, drain: bool = False) -> bool:
        return self._live_sessions.stop_session(session_id, drain=drain)

    def remove_live_session(self, session_id: str) -> bool:
        return self._live_sessions.remove_session(session_id)

    def stop_all_live_sessions(self, *, drain: bool = False) -> None:
        self._live_sessions.stop_all(drain=drain)

    def active_live_count(self) -> int:
        return self._live_sessions.active_count()

    # Legacy compatibility API. A start now adds a session rather than
    # replacing the previously active Live pipeline.
    def start_transcription(
        self,
        sink_name=None,
        audio_source=None,
        language=None,
        stream_id: Optional[int] = None,
    ) -> dict[str, Any]:
        return self.start_live_session(
            sink_name=sink_name,
            audio_source=audio_source,
            language=language,
            stream_id=stream_id,
        )

    def stop_transcription(self) -> None:
        self.stop_all_live_sessions(drain=False)

    def stop_listening(self) -> None:
        self.stop_all_live_sessions(drain=True)

    def is_running(self) -> bool:
        return any(
            not bool(item.get("terminal")) and not bool(item.get("draining"))
            for item in self._live_sessions.list_sessions()
        )

    def is_draining(self) -> bool:
        return any(
            bool(item.get("draining")) and not bool(item.get("terminal"))
            for item in self._live_sessions.list_sessions()
        )

    # ------------------------------------------------------------------
    # File transcription (exclusive from Live sessions)
    # ------------------------------------------------------------------
    def start_file_transcription(
        self,
        file_path: str,
        language: Optional[str] = None,
        model_size: Optional[str] = None,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
        history_source: str = "file",
    ) -> None:
        if self._live_sessions.has_active_sessions():
            raise RuntimeError(
                "Ferma le sessioni Live prima di avviare una trascrizione file"
            )
        self.stop_file_transcription()
        generation = self._next_generation()
        lang = language or self._settings.language
        cfg = (
            self._settings.with_(model_size=model_size)
            if model_size and model_size != self._settings.model_size
            else self._settings
        )
        self._start_history_session(
            model=cfg.model_size,
            language=lang,
            source=history_source,
            source_path=str(file_path),
        )

        def start() -> None:
            # Stop/Start and shutdown invalidate older generations. Check before
            # doing expensive model/backend work so a stale queued startup can
            # never resurrect whisper-server after the user has stopped it.
            if not self._is_current(generation):
                return
            self.ensure_backend_started(
                vad=False if song_mode else cfg.vad_filter,
                settings=cfg,
            )
            if not self._is_current(generation):
                return
            worker = FileTranscriberThread(
                file_path,
                self._backend,
                cfg,
                song_mode=song_mode,
                isolate_vocals_flag=isolate_vocals_flag,
                language=lang,
            )
            with self._lock:
                if generation != self._generation:
                    return
                self._file_thread = worker
            worker.start()

        self._run_async(generation, start, "file_transcriber_error")

    def start_recovery_transcription(self, recovery_path: str) -> None:
        if self._live_sessions.has_active_sessions() or self.is_file_busy():
            raise RuntimeError(
                "Ferma la trascrizione attiva prima di recuperare l'audio"
            )
        path = self._history.resolve_recovery_audio(recovery_path)
        self.start_file_transcription(
            str(path),
            language=self._settings.language,
            model_size=self._settings.model_size,
            song_mode=False,
            isolate_vocals_flag=False,
            history_source="recovery",
        )

    def stop_file_transcription(self) -> None:
        self._next_generation()
        with self._lock:
            worker = self._file_thread
            self._file_thread = None
        if worker:
            worker.stop()
            if worker.is_alive():
                # File mode is exclusive from Live sessions, therefore aborting
                # the active request cannot terminate another Live pipeline.
                self._backend.abort_active_request()
                self._backend_started = False
            if worker is not threading.current_thread():
                worker.join(timeout=5.0)
        self._finish_history_session(StatusEnum.STOPPED.value)

    def is_file_transcribing(self) -> bool:
        worker = self._file_thread
        return bool(worker and worker.is_alive())

    def is_file_busy(self) -> bool:
        """Return whether a File worker is running or still starting."""
        if self.is_file_transcribing():
            return True
        startup = self._startup_thread
        return bool(startup and startup.is_alive())

    # ------------------------------------------------------------------
    # Settings, models and discovery
    # ------------------------------------------------------------------
    def update_settings(self, **overrides: object) -> None:
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        self._bus.emit("config_changed", overrides)
        if "history_retention_days" in overrides:
            deleted = self.prune_history()
            if deleted:
                self._bus.emit("history_changed", None)

    def list_models(self) -> list[dict[str, object]]:
        return self._model_manager.list_ui_models()

    def list_playback_streams(self) -> list[dict[str, Any]]:
        return [stream.to_dict() for stream in self._audio_router.list_streams()]

    def download_model(self, model_size: str) -> str:
        self._require_idle_for_model_operation()
        if model_size not in self._model_manager.ui_model_choices():
            raise ValueError(f"modello UI non valido: {model_size}")
        if not self._model_operation_lock.acquire(blocking=False):
            raise RuntimeError("Un'altra operazione sui modelli è già in corso")
        try:
            self._bus.emit("model_download_started", {"model": model_size})

            def progress(downloaded: int, total: Optional[int]) -> None:
                percent = None
                if total and total > 0:
                    percent = min(100, int(downloaded * 100 / total))
                self._bus.emit(
                    "model_download_progress",
                    {
                        "model": model_size,
                        "downloaded": downloaded,
                        "total": total,
                        "percent": percent,
                    },
                )

            path = self._model_manager.download_model(model_size, progress)
            self._bus.emit(
                "model_status_changed",
                {"model": model_size, "action": "downloaded"},
            )
            return str(path)
        finally:
            self._model_operation_lock.release()

    def delete_model(self, model_size: str) -> bool:
        self._require_idle_for_model_operation()
        if model_size not in self._model_manager.ui_model_choices():
            raise ValueError(f"modello UI non valido: {model_size}")
        if not self._model_operation_lock.acquire(blocking=False):
            raise RuntimeError("Un'altra operazione sui modelli è già in corso")
        try:
            if self._backend.is_running:
                self.stop_backend()
            deleted = self._model_manager.delete_model(model_size)
            self._bus.emit(
                "model_status_changed",
                {"model": model_size, "action": "deleted", "deleted": deleted},
            )
            return deleted
        finally:
            self._model_operation_lock.release()

    def _require_idle_for_model_operation(self) -> None:
        if self._live_sessions.has_active_sessions() or self.is_file_busy():
            raise RuntimeError(
                "Ferma la trascrizione attiva prima di gestire i modelli"
            )

    # ------------------------------------------------------------------
    # History and recovery
    # ------------------------------------------------------------------
    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        self.prune_history()
        return self._history.list_recent(limit)

    def get_history_session(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._history.get_session(session_id)

    def export_history_session(self, session_id: str, target_path: str) -> str:
        return str(self._history.export_text(session_id, target_path))

    def delete_history_session(self, session_id: str) -> bool:
        live = self._live_sessions.get_session(session_id)
        if live is not None and not bool(live.get("terminal")):
            raise RuntimeError("Non puoi eliminare una sessione ancora attiva")
        with self._lock:
            if session_id == self._file_history_id:
                raise RuntimeError("Non puoi eliminare una sessione ancora attiva")
        deleted = self._history.delete_session(session_id)
        if deleted:
            self._bus.emit("history_changed", session_id)
        return deleted

    def prune_history(self) -> int:
        deleted = self._history.prune_older_than(
            self._settings.history_retention_days
        )
        if deleted:
            logger.info("Retention cronologia: eliminate %d sessioni", deleted)
        return deleted

    def list_recovery_audio(self) -> list[dict[str, Any]]:
        return self._history.list_recovery_audio()

    def delete_recovery_audio(self, recovery_path: str) -> bool:
        if self.is_file_busy():
            raise RuntimeError(
                "Ferma la trascrizione file prima di eliminare un recovery"
            )
        deleted = self._history.delete_recovery_audio(recovery_path)
        if deleted:
            self._bus.emit("history_changed", None)
        return deleted

    # ------------------------------------------------------------------
    # Lifecycle and helpers
    # ------------------------------------------------------------------
    def subscribe(self, event: str, handler: Callable) -> None:
        self._bus.subscribe(event, handler)

    def shutdown(self) -> None:
        self._file_batch.close()
        self._meeting.shutdown()
        self.stop_file_transcription()
        self._live_sessions.shutdown()
        self.stop_backend()
        for event, handler in self._history_subscriptions:
            self._bus.unsubscribe(event, handler)
        self._history_subscriptions.clear()

    def _resolve_sink(self, sink_name: Optional[str], audio_source: str) -> str:
        if sink_name is not None:
            return sink_name
        if audio_source == AudioSource.APPLICATION.value:
            raise SinkNotFoundError(
                "Per la sorgente Applicazione devi selezionare uno stream",
                detail="Scegli uno stream attivo dall'elenco delle applicazioni.",
            )
        found = find_source(self._settings, audio_source=audio_source)
        if found is not None:
            return found
        if audio_source == AudioSource.SYSTEM.value:
            raise SinkNotFoundError(
                "Impossibile trovare automaticamente l'audio di sistema",
                detail=(
                    "Verifica che PipeWire/PulseAudio abbia un'uscita "
                    "predefinita oppure seleziona manualmente un monitor."
                ),
            )
        raise SinkNotFoundError(
            "Impossibile trovare automaticamente il microfono",
            detail="Assicurati che il microfono sia collegato e funzionante",
        )

    def _subscribe_history_events(self) -> None:
        # Live history is owned directly by LiveSessionManager. Only the
        # singleton File worker still uses global EventBus history hooks.
        handlers: tuple[tuple[str, Callable[[Any], None]], ...] = (
            (
                "file_transcriber_new_text",
                lambda payload: self._append_file_history_text(payload),
            ),
            ("file_transcriber_status_changed", self._on_file_history_status),
            (
                "file_transcriber_error",
                lambda _payload: self._finish_history_session(StatusEnum.ERROR.value),
            ),
            (
                "file_transcriber_completed",
                lambda _payload: self._finish_history_session(StatusEnum.COMPLETED.value),
            ),
        )
        for event, handler in handlers:
            self._bus.subscribe(event, handler)
            self._history_subscriptions.append((event, handler))

    def _start_history_session(self, **metadata: Any) -> None:
        try:
            session_id = self._history.create_session(kind="file", **metadata)
        except Exception as exc:
            logger.exception("Impossibile creare la cronologia file")
            self._bus.emit("history_error", str(exc))
            return
        with self._lock:
            self._file_history_id = session_id
        self._bus.emit("history_changed", session_id)

    def _append_file_history_text(self, payload: Any) -> None:
        with self._lock:
            session_id = self._file_history_id
        if session_id is None:
            return
        try:
            self._history.append_text(session_id, str(payload or ""))
        except Exception as exc:
            logger.exception("Autosave trascrizione file fallito")
            self._bus.emit("history_error", str(exc))

    def _set_file_history_status(self, status: str) -> None:
        with self._lock:
            session_id = self._file_history_id
        if session_id is None:
            return
        try:
            self._history.set_status(session_id, status)
        except Exception as exc:
            logger.exception("Aggiornamento cronologia file fallito")
            self._bus.emit("history_error", str(exc))

    def _finish_history_session(self, status: str) -> None:
        with self._lock:
            session_id = self._file_history_id
            self._file_history_id = None
        if session_id is None:
            return
        try:
            self._history.set_status(session_id, status, terminal=True)
        except Exception as exc:
            logger.exception("Chiusura cronologia file fallita")
            self._bus.emit("history_error", str(exc))
            return
        self._bus.emit("history_changed", session_id)

    def _on_file_history_status(self, payload: Any) -> None:
        status = str(payload)
        terminal = {
            StatusEnum.COMPLETED.value,
            StatusEnum.STOPPED.value,
            StatusEnum.ERROR.value,
        }
        if status in terminal:
            self._finish_history_session(status)
        else:
            self._set_file_history_status(status)
