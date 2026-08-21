"""Loss-resistant live transcription worker."""
from __future__ import annotations
import logging, struct, threading, time
from queue import Empty
import numpy as np
from config.constants import AppMeta, ProcessDefaults, SYCLDefaults
from config.settings import Settings
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.models import StatusEnum
from core.text_dedup import deduplicate_text, remove_chunk_overlap
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)

class TranscriberThread(threading.Thread):
    def __init__(self, buffer: BufferManager, backend: WhisperBackend, settings: Settings) -> None:
        super().__init__(daemon=True, name="TranscriberThread")
        self._buffer, self._backend, self._settings = buffer, backend, settings
        self._stop_event = threading.Event()
        self._current_segment: list[np.ndarray] = []
        self._segment_sample_count = 0
        self._segment_samples = int(settings.sample_rate * ProcessDefaults.SEGMENT_LENGTH_S)
        self._min_segment_samples = int(settings.sample_rate * ProcessDefaults.MIN_SEGMENT_S)
        self._overlap_samples = int(settings.sample_rate * ProcessDefaults.OVERLAP_DURATION_S)
        self._overlap_buffer = np.array([], dtype=np.float32)
        self._last_emitted_text = ""
        self._terminal_error = False

    def run(self) -> None:
        bus = EventBus()
        bus.emit("transcriber_status_changed", StatusEnum.RUNNING.value)
        drained = False
        try:
            drained = self._loop()
        except Exception as exc:
            self._terminal_error = True
            if not self._stop_event.is_set():
                logger.exception("Errore trascrizione live")
                bus.emit("transcriber_error", f"Errore trascrizione: {exc}")
                bus.emit("transcriber_status_changed", StatusEnum.ERROR.value)
        finally:
            if drained and not self._stop_event.is_set():
                try:
                    self._flush_segment(final=True)
                except Exception as exc:
                    self._terminal_error = True
                    bus.emit("transcriber_error", f"Errore flush finale: {exc}")
                    bus.emit("transcriber_status_changed", StatusEnum.ERROR.value)
                else:
                    bus.emit("transcriber_drained", None)
            elif self._stop_event.is_set() and self._current_segment:
                self._persist_recovery_audio()
            if not self._terminal_error:
                bus.emit("transcriber_status_changed", StatusEnum.STOPPED.value)

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> bool:
        bus = EventBus()
        while not self._stop_event.is_set():
            try:
                chunk = self._buffer.get(timeout=0.5)
            except Empty:
                if self._buffer.input_closed and self._buffer.is_empty:
                    return True
                bus.emit("transcriber_buffer_level", self._buffer.buffer_level)
                continue
            self._current_segment.append(np.asarray(chunk, dtype=np.float32).reshape(-1))
            self._segment_sample_count += chunk.shape[0]
            bus.emit("transcriber_buffer_level", self._buffer.buffer_level)
            if self._segment_sample_count >= self._segment_samples:
                self._flush_segment(final=False)
        return False

    def _flush_segment(self, final: bool) -> None:
        if not self._current_segment:
            return
        if self._segment_sample_count < self._min_segment_samples and not final:
            return
        body = np.concatenate(self._current_segment)
        overlap = self._overlap_buffer
        audio = np.concatenate((overlap, body)) if overlap.size else body
        if self._is_silent(audio):
            self._commit_segment(body, final)
            return
        text = self._transcribe_with_retry(audio)
        cleaned = remove_chunk_overlap(self._last_emitted_text, text)
        cleaned = deduplicate_text(cleaned)
        if cleaned:
            EventBus().emit("transcriber_new_text", cleaned)
            self._last_emitted_text = (self._last_emitted_text + " " + cleaned).strip()[-1200:]
        self._commit_segment(body, final)

    def _commit_segment(self, body: np.ndarray, final: bool) -> None:
        self._current_segment.clear()
        self._segment_sample_count = 0
        if not final and self._overlap_samples > 0 and body.size > self._overlap_samples:
            self._overlap_buffer = body[-self._overlap_samples:].copy()
        else:
            self._overlap_buffer = np.array([], dtype=np.float32)

    def _transcribe_with_retry(self, audio: np.ndarray) -> str:
        wav = self._numpy_to_wav(audio)
        prompt = self._last_emitted_text[-500:] or None
        last: Exception | None = None
        for attempt in range(3):
            if self._stop_event.is_set():
                raise RuntimeError("trascrizione interrotta")
            try:
                result = self._backend.transcribe_audio(
                    wav, language=self._settings.language, prompt=prompt,
                    verbose=False, timeout=SYCLDefaults.LIVE_REQUEST_TIMEOUT_S,
                    vad=self._settings.vad_filter,
                )
                return result if isinstance(result, str) else str(result.get("text", ""))
            except RuntimeError as exc:
                last = exc
                if attempt < 2:
                    self._stop_event.wait(ProcessDefaults.TRANSCRIBE_RETRY_DELAY_S)
        self._persist_recovery_audio(audio)
        raise RuntimeError(f"segmento live non trascritto dopo 3 tentativi: {last}")

    def _persist_recovery_audio(self, audio: np.ndarray | None = None) -> None:
        if audio is None:
            parts = ([self._overlap_buffer] if self._overlap_buffer.size else []) + self._current_segment
            if not parts:
                return
            audio = np.concatenate(parts)
        try:
            AppMeta.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = AppMeta.CACHE_DIR / f"recovery-live-{int(time.time())}.wav"
            path.write_bytes(self._numpy_to_wav(audio))
            logger.warning("Audio non trascritto salvato per recupero: %s", path)
            EventBus().emit("recovery_audio_saved", str(path))
        except OSError:
            logger.exception("Impossibile salvare recovery audio")

    @staticmethod
    def _numpy_to_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
            1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", len(pcm),
        )
        return header + pcm

    @staticmethod
    def _compute_rms(audio: np.ndarray) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))

    def _is_silent(self, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return True
        win = max(1, self._settings.sample_rate // 2)
        peak = 0.0
        for i in range(0, audio.size, win):
            peak = max(peak, self._compute_rms(audio[i:i + win]))
        return peak < ProcessDefaults.SILENCE_RMS_THRESHOLD
