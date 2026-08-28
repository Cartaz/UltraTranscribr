"""Low-latency microphone dictation pipeline independent from normal Live sessions."""
from __future__ import annotations

import logging
import struct
import threading
from collections import deque
from queue import Empty
from typing import Any, Callable, Protocol

import numpy as np

from config.constants import DictationDefaults, ProcessDefaults
from config.settings import AudioSource, Settings
from core.audio_capture import AudioCaptureThread
from core.buffer_manager import BufferManager
from core.dictation_stability import StablePrefixCommitter

logger = logging.getLogger(__name__)
EventSink = Callable[[str, Any], None]
BackendInitializer = Callable[[Settings], None]
CaptureFactory = Callable[..., AudioCaptureThread]


class DictationBackend(Protocol):
    def transcribe_audio(self, *args: Any, **kwargs: Any) -> str | dict: ...


class DictationTranscriberThread(threading.Thread):
    """Run rolling-window Whisper requests and emit only stable text deltas."""

    def __init__(
        self,
        buffer: BufferManager,
        backend: DictationBackend,
        settings: Settings,
        *,
        event_sink: EventSink,
    ) -> None:
        super().__init__(daemon=True, name="DictationTranscriber")
        self._buffer = buffer
        self._backend = backend
        self._settings = settings
        self._emit = event_sink
        self._stop_event = threading.Event()
        self._window: deque[np.ndarray] = deque()
        self._window_samples = 0
        self._since_inference = 0
        self._max_samples = int(settings.sample_rate * DictationDefaults.WINDOW_MS / 1000)
        self._step_samples = int(settings.sample_rate * DictationDefaults.STEP_MS / 1000)
        self._min_samples = int(settings.sample_rate * DictationDefaults.MIN_AUDIO_MS / 1000)
        self._committer = StablePrefixCommitter()
        self._had_new_audio = False

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        drained = False
        try:
            drained = self._consume()
            if drained and not self._stop_event.is_set() and self._had_new_audio:
                self._infer(force=True)
            if drained and not self._stop_event.is_set():
                final = self._committer.finalize()
                if final.committed_delta:
                    self._emit("dictation_text_committed", final.committed_delta)
                self._emit(
                    "dictation_preview_changed",
                    {
                        "committed": final.committed_text,
                        "pending": "",
                        "hypothesis": final.hypothesis,
                    },
                )
                self._emit("dictation_final_text", final.committed_text)
                self._emit("dictation_transcriber_drained", None)
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.exception("Errore transcriber dettatura")
                self._emit("dictation_error", str(exc))

    def _consume(self) -> bool:
        while not self._stop_event.is_set():
            try:
                chunk = self._buffer.get(timeout=0.25)
            except Empty:
                if self._buffer.input_closed and self._buffer.is_empty:
                    return True
                continue
            arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if not arr.size:
                continue
            self._window.append(arr)
            self._window_samples += arr.size
            self._since_inference += arr.size
            self._had_new_audio = True
            self._trim_window()
            if self._window_samples >= self._min_samples and self._since_inference >= self._step_samples:
                self._infer(force=False)
        return False

    def _trim_window(self) -> None:
        excess = self._window_samples - self._max_samples
        while excess > 0 and self._window:
            first = self._window[0]
            if first.size <= excess:
                self._window.popleft()
                self._window_samples -= first.size
                excess -= first.size
            else:
                self._window[0] = first[excess:].copy()
                self._window_samples -= excess
                excess = 0

    def _infer(self, *, force: bool) -> None:
        if not self._window:
            return
        audio = np.concatenate(tuple(self._window))
        if not force and self._is_silent(audio):
            self._since_inference = 0
            self._had_new_audio = False
            return
        if force and self._is_silent(audio):
            return
        result = self._backend.transcribe_audio(
            self._numpy_to_wav(audio, self._settings.sample_rate),
            language=self._settings.language,
            prompt=self._committer.committed_text[-DictationDefaults.PROMPT_CHARS:] or None,
            verbose=False,
            timeout=DictationDefaults.REQUEST_TIMEOUT_S,
            vad=False,
            on_queue_wait=lambda ms: self._emit("dictation_queue_wait", float(ms)),
        )
        text = result if isinstance(result, str) else str(result.get("text", ""))
        update = self._committer.update(text)
        if update.committed_delta:
            self._emit("dictation_text_committed", update.committed_delta)
        self._emit(
            "dictation_preview_changed",
            {
                "committed": update.committed_text,
                "pending": update.pending_text,
                "hypothesis": update.hypothesis,
            },
        )
        self._since_inference = 0
        self._had_new_audio = False

    @staticmethod
    def _is_silent(audio: np.ndarray) -> bool:
        if audio.size == 0:
            return True
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
        return rms < ProcessDefaults.SILENCE_RMS_THRESHOLD

    @staticmethod
    def _numpy_to_wav(audio: np.ndarray, sample_rate: int) -> bytes:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(pcm),
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            sample_rate,
            sample_rate * 2,
            2,
            16,
            b"data",
            len(pcm),
        ) + pcm


class DictationService:
    """Own Dictation capture/transcriber lifecycle and its canonical runtime state."""

    def __init__(
        self,
        *,
        backend: DictationBackend,
        backend_initializer: BackendInitializer,
        event_sink: EventSink,
        capture_factory: CaptureFactory = AudioCaptureThread,
    ) -> None:
        self._backend = backend
        self._backend_initializer = backend_initializer
        self._emit = event_sink
        self._capture_factory = capture_factory
        self._lock = threading.RLock()
        self._generation = 0
        self._requested = False
        self._closed = False
        self._status = "idle"
        self._settings: Settings | None = None
        self._buffer: BufferManager | None = None
        self._capture: AudioCaptureThread | None = None
        self._transcriber: DictationTranscriberThread | None = None
        self._startup: threading.Thread | None = None
        self._cleanup: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "requested": self._requested,
                "capture_running": bool(self._capture and self._capture.is_alive()),
                "transcriber_running": bool(self._transcriber and self._transcriber.is_alive()),
                "closed": self._closed,
            }

    def set_active(self, active: bool, settings: Settings) -> None:
        if active:
            self._request_start(settings)
        else:
            self._request_stop()

    def _request_start(self, settings: Settings) -> None:
        with self._lock:
            if self._closed:
                return
            self._requested = True
            self._settings = settings
            if self._status in {"starting", "listening", "finalizing"}:
                return
            self._generation += 1
            generation = self._generation
            self._status = "starting"
            self._publish_state_locked()
            worker = threading.Thread(
                target=self._startup_worker,
                args=(generation, settings),
                daemon=True,
                name="DictationStartup",
            )
            self._startup = worker
            worker.start()

    def _startup_worker(self, generation: int, settings: Settings) -> None:
        buffer: BufferManager | None = None
        capture: AudioCaptureThread | None = None
        transcriber: DictationTranscriberThread | None = None
        try:
            dictation_settings = settings.with_(
                audio_source=AudioSource.MICROPHONE.value,
                chunk_ms=DictationDefaults.CAPTURE_CHUNK_MS,
                sink_name=None,
                live_microphone_recording=False,
            )
            self._backend_initializer(dictation_settings)
            with self._lock:
                if not self._can_start_locked(generation):
                    return
            buffer = BufferManager(warn_threshold=max(4, settings.buffer_warn_threshold))
            transcriber = DictationTranscriberThread(
                buffer,
                self._backend,
                dictation_settings,
                event_sink=self._handle_worker_event,
            )
            capture = self._capture_factory(
                buffer,
                dictation_settings,
                device_name=None,
                audio_source=AudioSource.MICROPHONE.value,
                session_id="dictation",
                event_sink=self._handle_capture_event,
            )
            with self._lock:
                if not self._can_start_locked(generation):
                    buffer.close_input()
                    buffer.close()
                    return
                self._buffer = buffer
                self._capture = capture
                self._transcriber = transcriber
                transcriber.start()
                capture.start()
                self._status = "listening"
                self._publish_state_locked()
        except Exception as exc:
            logger.exception("Avvio dettatura fallito")
            if buffer is not None:
                buffer.close_input()
                buffer.close()
            with self._lock:
                if generation == self._generation and not self._closed:
                    self._requested = False
                    self._status = "error"
                    self._publish_state_locked()
            self._emit("dictation_error", str(exc))
        finally:
            with self._lock:
                if self._startup is threading.current_thread():
                    self._startup = None

    def _request_stop(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._requested = False
            self._generation += 1
            capture = self._capture
            buffer = self._buffer
            transcriber = self._transcriber
            if capture is None and transcriber is None:
                self._status = "idle"
                self._publish_state_locked()
                return
            if self._status != "finalizing":
                self._status = "finalizing"
                self._publish_state_locked()
            if capture is not None:
                capture.stop()
            if buffer is not None:
                buffer.close_input()
            self._start_cleanup_locked(capture, transcriber, buffer, preserve_error=False)

    def _handle_capture_event(self, event: str, payload: Any) -> None:
        if event == "transcriber_error":
            self._handle_runtime_error(str(payload or "errore cattura audio"))
        else:
            self._emit(event, payload)

    def _handle_worker_event(self, event: str, payload: Any) -> None:
        if event == "dictation_error":
            self._handle_runtime_error(str(payload or "errore trascrizione"))
            return
        self._emit(event, payload)

    def _handle_runtime_error(self, message: str) -> None:
        with self._lock:
            if self._closed or self._status == "error":
                return
            self._requested = False
            self._generation += 1
            self._status = "error"
            capture = self._capture
            buffer = self._buffer
            transcriber = self._transcriber
            if capture is not None:
                capture.stop()
            if buffer is not None:
                buffer.close_input()
            self._publish_state_locked()
            self._start_cleanup_locked(capture, transcriber, buffer, preserve_error=True)
        self._emit("dictation_error", message)

    def _start_cleanup_locked(
        self,
        capture: AudioCaptureThread | None,
        transcriber: DictationTranscriberThread | None,
        buffer: BufferManager | None,
        *,
        preserve_error: bool,
    ) -> None:
        if self._cleanup is not None and self._cleanup.is_alive():
            return
        cleanup = threading.Thread(
            target=self._cleanup_worker,
            args=(capture, transcriber, buffer, preserve_error),
            daemon=True,
            name="DictationCleanup",
        )
        self._cleanup = cleanup
        cleanup.start()

    def _cleanup_worker(
        self,
        capture: AudioCaptureThread | None,
        transcriber: DictationTranscriberThread | None,
        buffer: BufferManager | None,
        preserve_error: bool,
    ) -> None:
        if capture is not None and capture is not threading.current_thread():
            capture.join(timeout=5.0)
        if buffer is not None:
            buffer.close_input()
        if transcriber is not None and transcriber is not threading.current_thread():
            transcriber.join(timeout=DictationDefaults.REQUEST_TIMEOUT_S + 5.0)
            if transcriber.is_alive():
                logger.warning("DictationTranscriber non drenato entro il limite; richiesta stop")
                transcriber.stop()
                transcriber.join(timeout=5.0)
        if buffer is not None:
            buffer.close()
        restart: Settings | None = None
        with self._lock:
            if self._capture is capture:
                self._capture = None
            if self._transcriber is transcriber:
                self._transcriber = None
            if self._buffer is buffer:
                self._buffer = None
            self._cleanup = None
            if self._closed:
                self._status = "closed"
            elif preserve_error:
                self._status = "error"
            elif self._requested and self._settings is not None:
                self._status = "idle"
                restart = self._settings
            else:
                self._status = "idle"
            self._publish_state_locked()
        if restart is not None:
            self._request_start(restart)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._requested = False
            self._generation += 1
            capture = self._capture
            transcriber = self._transcriber
            buffer = self._buffer
            startup = self._startup
            cleanup = self._cleanup
            if capture is not None:
                capture.stop()
            if buffer is not None:
                buffer.close_input()
        if startup is not None and startup.is_alive() and startup is not threading.current_thread():
            startup.join(timeout=5.0)
        if cleanup is not None and cleanup.is_alive() and cleanup is not threading.current_thread():
            cleanup.join(timeout=DictationDefaults.REQUEST_TIMEOUT_S + 10.0)
        else:
            if capture is not None and capture is not threading.current_thread():
                capture.join(timeout=5.0)
            if transcriber is not None and transcriber is not threading.current_thread():
                transcriber.stop()
                transcriber.join(timeout=5.0)
            if buffer is not None:
                buffer.close()
        with self._lock:
            self._capture = None
            self._transcriber = None
            self._buffer = None
            self._status = "closed"
            self._publish_state_locked()

    def _can_start_locked(self, generation: int) -> bool:
        return not self._closed and self._requested and generation == self._generation

    def _publish_state_locked(self) -> None:
        payload = {
            "status": self._status,
            "requested": self._requested,
            "capture_running": bool(self._capture and self._capture.is_alive()),
            "transcriber_running": bool(self._transcriber and self._transcriber.is_alive()),
            "closed": self._closed,
        }
        self._emit("dictation_session_changed", payload)
