"""Application controller with race-safe worker lifecycle."""
from __future__ import annotations
import logging, threading
from pathlib import Path
from typing import Callable, Optional
from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.exceptions import GPUNotAvailableError, SinkNotFoundError
from core.file_transcriber import FileTranscriberThread
from core.models import StatusEnum
from core.sink_finder import find_source
from core.transcriber import TranscriberThread
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
        self._capture_thread: Optional[AudioCaptureThread] = None
        self._transcriber_thread: Optional[TranscriberThread] = None
        self._file_thread: Optional[FileTranscriberThread] = None
        self._startup_thread: Optional[threading.Thread] = None
        self._backend_started = False
        self._lock = threading.RLock()
        self._backend_init_lock = threading.Lock()
        self._generation = 0

    @property
    def settings(self): return self._settings
    @property
    def buffer(self): return self._buffer
    @property
    def backend(self): return self._backend

    def _next_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def ensure_backend_started(self, *, vad: Optional[bool] = None,
                               settings: Optional[Settings] = None) -> None:
        cfg = settings or self._settings
        wanted = cfg.vad_filter if vad is None else bool(vad)
        with self._backend_init_lock:
            with self._lock:
                already = self._backend_started and self._backend.is_running
            vad_path = self._model_manager.get_vad_model_path() if wanted else None
            if already:
                self._backend.ensure_vad_mode(wanted, vad_path)
                return
            self._bus.emit("backend_status_changed", StatusEnum.LOADING_MODEL.value)
            model = self._model_manager.get_model_path(cfg.model_size)
            self._backend.start(model, vad_path)
            self._backend.ensure_vad_mode(wanted, vad_path)
            with self._lock:
                self._backend_started = True

    def stop_backend(self) -> None:
        with self._lock:
            self._backend.stop()
            self._backend_started = False

    def _run_async(self, generation: int, target: Callable[[], None], error_event: str) -> None:
        def wrapped() -> None:
            try:
                target()
            except Exception as exc:
                logger.exception("Avvio asincrono fallito")
                if self._is_current(generation):
                    self._bus.emit(error_event, str(exc))
                    if error_event == "transcriber_error":
                        self._bus.emit("process_stopped", None)
                    else:
                        self._bus.emit("file_transcriber_status_changed", StatusEnum.ERROR.value)
            finally:
                with self._lock:
                    if self._startup_thread is threading.current_thread():
                        self._startup_thread = None
        t = threading.Thread(target=wrapped, daemon=True, name="ControllerStartup")
        with self._lock:
            self._startup_thread = t
        t.start()

    def start_transcription(self, sink_name=None, audio_source=None, language=None) -> None:
        self.stop_file_transcription()
        self.stop_transcription()
        generation = self._next_generation()
        src = audio_source or self._settings.audio_source
        sink = self._resolve_sink(sink_name, src)
        lang = language or self._settings.language
        self._buffer.clear()
        def start() -> None:
            self.ensure_backend_started(vad=self._settings.vad_filter)
            if not self._is_current(generation):
                return
            cap = AudioCaptureThread(self._buffer, self._settings, sink, src)
            tx = TranscriberThread(self._buffer, self._backend, self._settings.with_(language=lang))
            with self._lock:
                if generation != self._generation:
                    return
                self._capture_thread = cap
                self._transcriber_thread = tx
            cap.start()
            tx.start()
            self._bus.emit("process_started", {"sink": sink, "source": src})
        self._run_async(generation, start, "transcriber_error")

    def stop_transcription(self) -> None:
        self._next_generation()
        with self._lock:
            cap, tx = self._capture_thread, self._transcriber_thread
            self._capture_thread = None
            self._transcriber_thread = None
        if cap:
            cap.stop()
        if tx:
            tx.stop()
        if tx and tx.is_alive():
            self._backend.abort_active_request()
            self._backend_started = False
        for t in (cap, tx):
            if t and t is not threading.current_thread():
                t.join(timeout=5.0)
        self._bus.emit("process_stopped", None)

    def stop_listening(self) -> None:
        with self._lock:
            cap = self._capture_thread
        if not cap:
            return
        cap.stop()
        if cap is not threading.current_thread():
            cap.join(timeout=5.0)
        with self._lock:
            self._capture_thread = None
        self._buffer.close_input()
        self._bus.emit("capture_stopped", None)

    def is_running(self) -> bool:
        c = self._capture_thread
        return bool(c and c.is_alive())

    def is_draining(self) -> bool:
        t = self._transcriber_thread
        return self._capture_thread is None and bool(t and t.is_alive())

    def start_file_transcription(self, file_path: str, language: Optional[str] = None,
                                 model_size: Optional[str] = None, song_mode: bool = False,
                                 isolate_vocals_flag: bool = False) -> None:
        self.stop_transcription()
        self.stop_file_transcription()
        generation = self._next_generation()
        lang = language or self._settings.language
        cfg = (self._settings.with_(model_size=model_size)
               if model_size and model_size != self._settings.model_size else self._settings)
        def start() -> None:
            self.ensure_backend_started(vad=False if song_mode else cfg.vad_filter, settings=cfg)
            if not self._is_current(generation):
                return
            worker = FileTranscriberThread(
                file_path, self._backend, cfg, song_mode=song_mode,
                isolate_vocals_flag=isolate_vocals_flag, language=lang,
            )
            with self._lock:
                if generation != self._generation:
                    return
                self._file_thread = worker
            worker.start()
        self._run_async(generation, start, "file_transcriber_error")

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

    def is_file_transcribing(self) -> bool:
        t = self._file_thread
        return bool(t and t.is_alive())

    def update_settings(self, **overrides: object) -> None:
        self._settings = self._settings.with_(**overrides)
        self._settings.save()
        self._bus.emit("config_changed", overrides)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._bus.subscribe(event, handler)

    def shutdown(self) -> None:
        self.stop_file_transcription()
        self.stop_transcription()
        self.stop_backend()
        self._buffer.close()

    def _resolve_sink(self, sink_name: Optional[str], audio_source: str) -> str:
        if sink_name is not None:
            return sink_name
        found = find_source(self._settings, audio_source=audio_source)
        if found is not None:
            return found
        if audio_source == AudioSource.FIREFOX.value:
            raise SinkNotFoundError(
                "Impossibile trovare automaticamente il sink di Firefox",
                detail="Assicurati che Firefox sia aperto e riproduca audio",
            )
        raise SinkNotFoundError(
            "Impossibile trovare automaticamente il microfono",
            detail="Assicurati che il microfono sia collegato e funzionante",
        )
