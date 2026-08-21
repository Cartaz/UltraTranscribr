"""Application controller with race-safe worker lifecycle."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.audio_routing import PulseAudioRouter, StreamRouteLease
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.exceptions import GPUNotAvailableError, SinkNotFoundError
from core.file_transcriber import FileTranscriberThread
from core.models import StatusEnum
from core.sink_finder import find_source
from core.transcriber import TranscriberThread
from core.transcript_history import TranscriptHistoryStore
from core.whisper_backend import WhisperBackend
from core.whisper_gpu_detect import detect_gpu_backend
from core.whisper_models import WhisperModelManager

logger = logging.getLogger(__name__)


class AppController:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._project_root = Path(__file__).resolve().parent.parent
        self._buffer = BufferManager(warn_threshold=settings.buffer_warn_threshold)
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
        self._capture_thread: Optional[AudioCaptureThread] = None
        self._transcriber_thread: Optional[TranscriberThread] = None
        self._file_thread: Optional[FileTranscriberThread] = None
        self._startup_thread: Optional[threading.Thread] = None
        self._active_route: Optional[StreamRouteLease] = None
        self._backend_started = False
        self._lock = threading.RLock()
        self._backend_init_lock = threading.Lock()
        self._model_operation_lock = threading.Lock()
        self._generation = 0
        self._live_history_id: Optional[str] = None
        self._file_history_id: Optional[str] = None
        self._history_subscriptions: list[tuple[str, Callable[[Any], None]]] = []
        self._subscribe_history_events()

    @property
    def settings(self):
        return self._settings

    @property
    def buffer(self):
        return self._buffer

    @property
    def backend(self):
        return self._backend

    @property
    def history(self):
        return self._history

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

    def stop_backend(self) -> None:
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
                    if error_event == "transcriber_error":
                        self._bus.emit("process_stopped", None)
                    else:
                        self._bus.emit(
                            "file_transcriber_status_changed",
                            StatusEnum.ERROR.value,
                        )
            finally:
                with self._lock:
                    if self._startup_thread is threading.current_thread():
                        self._startup_thread = None

        t = threading.Thread(target=wrapped, daemon=True, name="ControllerStartup")
        with self._lock:
            self._startup_thread = t
        t.start()

    def start_transcription(
        self,
        sink_name=None,
        audio_source=None,
        language=None,
        stream_id: Optional[int] = None,
    ) -> None:
        self.stop_file_transcription()
        self.stop_transcription()
        generation = self._next_generation()
        src = audio_source or self._settings.audio_source
        lang = language or self._settings.language
        selected_stream = None

        if src == AudioSource.APPLICATION.value:
            if stream_id is None:
                raise SinkNotFoundError(
                    "Seleziona uno stream applicazione da trascrivere",
                    detail="Aggiorna l'elenco delle applicazioni in riproduzione e scegli uno stream.",
                )
            selected_stream = self._audio_router.get_stream(int(stream_id))
            sink = None
            history_path = selected_stream.display_name
        else:
            sink = self._resolve_sink(sink_name, src)
            history_path = sink

        self._buffer.clear()
        self._start_history_session(
            "live",
            model=self._settings.model_size,
            language=lang,
            source=src,
            source_path=history_path,
        )

        def start() -> None:
            route: Optional[StreamRouteLease] = None
            try:
                self.ensure_backend_started(vad=self._settings.vad_filter)
                if not self._is_current(generation):
                    return

                capture_sink = sink
                if src == AudioSource.APPLICATION.value:
                    assert stream_id is not None
                    self._bus.emit(
                        "playback_stream_status_changed",
                        {
                            "status": "isolating",
                            "selected_stream_id": int(stream_id),
                        },
                    )
                    route = self._audio_router.isolate_stream(
                        int(stream_id),
                        status_callback=self._on_playback_route_status,
                    )
                    capture_sink = route.monitor_name

                if not self._is_current(generation):
                    if route is not None:
                        route.close()
                    return

                cap = AudioCaptureThread(
                    self._buffer,
                    self._settings,
                    capture_sink,
                    src,
                )
                tx = TranscriberThread(
                    self._buffer,
                    self._backend,
                    self._settings.with_(language=lang),
                )
                with self._lock:
                    if generation != self._generation:
                        if route is not None:
                            route.close()
                        return
                    self._capture_thread = cap
                    self._transcriber_thread = tx
                    self._active_route = route

                cap.start()
                tx.start()
                payload: dict[str, Any] = {
                    "sink": capture_sink,
                    "source": src,
                }
                if selected_stream is not None:
                    payload["stream"] = selected_stream.to_dict()
                self._bus.emit("process_started", payload)
            except Exception:
                if route is not None:
                    with self._lock:
                        if self._active_route is route:
                            self._active_route = None
                    route.close()
                raise

        self._run_async(generation, start, "transcriber_error")

    def stop_transcription(self) -> None:
        self._next_generation()
        with self._lock:
            cap = self._capture_thread
            tx = self._transcriber_thread
            route = self._active_route
            self._capture_thread = None
            self._transcriber_thread = None
            self._active_route = None
        if cap:
            cap.stop()
        if tx:
            tx.stop()
        if tx and tx.is_alive():
            self._backend.abort_active_request()
            self._backend_started = False
        for worker in (cap, tx):
            if worker and worker is not threading.current_thread():
                worker.join(timeout=5.0)
        if route:
            route.close()
            self._bus.emit(
                "playback_stream_status_changed",
                {"status": "restored"},
            )
        self._bus.emit("process_stopped", None)

    def stop_listening(self) -> None:
        with self._lock:
            cap = self._capture_thread
            route = self._active_route
        if not cap:
            return
        cap.stop()
        if cap is not threading.current_thread():
            cap.join(timeout=5.0)
        with self._lock:
            self._capture_thread = None
            self._active_route = None
        if route:
            route.close()
            self._bus.emit(
                "playback_stream_status_changed",
                {"status": "restored"},
            )
        self._buffer.close_input()
        self._bus.emit("capture_stopped", None)

    def is_running(self) -> bool:
        capture = self._capture_thread
        return bool(capture and capture.is_alive())

    def is_draining(self) -> bool:
        transcriber = self._transcriber_thread
        return self._capture_thread is None and bool(
            transcriber and transcriber.is_alive()
        )

    def start_file_transcription(
        self,
        file_path: str,
        language: Optional[str] = None,
        model_size: Optional[str] = None,
        song_mode: bool = False,
        isolate_vocals_flag: bool = False,
        history_source: str = "file",
    ) -> None:
        self.stop_transcription()
        self.stop_file_transcription()
        generation = self._next_generation()
        lang = language or self._settings.language
        cfg = (
            self._settings.with_(model_size=model_size)
            if model_size and model_size != self._settings.model_size
            else self._settings
        )
        self._start_history_session(
            "file",
            model=cfg.model_size,
            language=lang,
            source=history_source,
            source_path=str(file_path),
        )

        def start() -> None:
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
        if self.is_running() or self.is_draining() or self.is_file_transcribing():
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
                self._backend.abort_active_request()
                self._backend_started = False
            if worker is not threading.current_thread():
                worker.join(timeout=5.0)
        self._finish_history_session("file", StatusEnum.STOPPED.value)

    def is_file_transcribing(self) -> bool:
        worker = self._file_thread
        return bool(worker and worker.is_alive())

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
        if self.is_running() or self.is_draining() or self.is_file_transcribing():
            raise RuntimeError(
                "Ferma la trascrizione attiva prima di gestire i modelli"
            )

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        self.prune_history()
        return self._history.list_recent(limit)

    def get_history_session(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._history.get_session(session_id)

    def export_history_session(self, session_id: str, target_path: str) -> str:
        return str(self._history.export_text(session_id, target_path))

    def delete_history_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in {self._live_history_id, self._file_history_id}:
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
        if self.is_file_transcribing():
            raise RuntimeError(
                "Ferma la trascrizione file prima di eliminare un recovery"
            )
        deleted = self._history.delete_recovery_audio(recovery_path)
        if deleted:
            self._bus.emit("history_changed", None)
        return deleted

    def subscribe(self, event: str, handler: Callable) -> None:
        self._bus.subscribe(event, handler)

    def shutdown(self) -> None:
        self.stop_file_transcription()
        self.stop_transcription()
        self.stop_backend()
        self._buffer.close()
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

    def _on_playback_route_status(self, payload: dict[str, Any]) -> None:
        self._bus.emit("playback_stream_status_changed", payload)

    def _subscribe_history_events(self) -> None:
        handlers: tuple[tuple[str, Callable[[Any], None]], ...] = (
            (
                "process_started",
                lambda _p: self._set_history_status(
                    "live", StatusEnum.RUNNING.value
                ),
            ),
            (
                "process_stopped",
                lambda _p: self._finish_history_session(
                    "live", StatusEnum.STOPPED.value
                ),
            ),
            (
                "capture_stopped",
                lambda _p: self._set_history_status("live", "draining"),
            ),
            (
                "transcriber_new_text",
                lambda p: self._append_history_text("live", p),
            ),
            (
                "transcriber_error",
                lambda _p: self._finish_history_session(
                    "live", StatusEnum.ERROR.value
                ),
            ),
            (
                "transcriber_drained",
                lambda _p: self._finish_history_session(
                    "live", StatusEnum.COMPLETED.value
                ),
            ),
            (
                "file_transcriber_new_text",
                lambda p: self._append_history_text("file", p),
            ),
            ("file_transcriber_status_changed", self._on_file_history_status),
            (
                "file_transcriber_error",
                lambda _p: self._finish_history_session(
                    "file", StatusEnum.ERROR.value
                ),
            ),
            (
                "file_transcriber_completed",
                lambda _p: self._finish_history_session(
                    "file", StatusEnum.COMPLETED.value
                ),
            ),
        )
        for event, handler in handlers:
            self._bus.subscribe(event, handler)
            self._history_subscriptions.append((event, handler))

    def _start_history_session(self, kind: str, **metadata: Any) -> None:
        try:
            session_id = self._history.create_session(kind=kind, **metadata)
        except Exception as exc:
            logger.exception("Impossibile creare la cronologia %s", kind)
            self._bus.emit("history_error", str(exc))
            return
        with self._lock:
            if kind == "live":
                self._live_history_id = session_id
            else:
                self._file_history_id = session_id
        self._bus.emit("history_changed", session_id)

    def _history_id(self, kind: str) -> Optional[str]:
        with self._lock:
            return (
                self._live_history_id
                if kind == "live"
                else self._file_history_id
            )

    def _append_history_text(self, kind: str, payload: Any) -> None:
        session_id = self._history_id(kind)
        if session_id is None:
            return
        try:
            self._history.append_text(session_id, str(payload or ""))
        except Exception as exc:
            logger.exception("Autosave trascrizione %s fallito", kind)
            self._bus.emit("history_error", str(exc))

    def _set_history_status(self, kind: str, status: str) -> None:
        session_id = self._history_id(kind)
        if session_id is None:
            return
        try:
            self._history.set_status(session_id, status)
        except Exception as exc:
            logger.exception("Aggiornamento cronologia %s fallito", kind)
            self._bus.emit("history_error", str(exc))

    def _finish_history_session(self, kind: str, status: str) -> None:
        with self._lock:
            if kind == "live":
                session_id = self._live_history_id
                self._live_history_id = None
            else:
                session_id = self._file_history_id
                self._file_history_id = None
        if session_id is None:
            return
        try:
            self._history.set_status(session_id, status, terminal=True)
        except Exception as exc:
            logger.exception("Chiusura cronologia %s fallita", kind)
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
            self._finish_history_session("file", status)
        else:
            self._set_history_status("file", status)
