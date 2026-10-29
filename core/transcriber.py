"""Loss-resistant live transcription worker."""

from __future__ import annotations

import logging
import os
import struct
import threading
import time
import wave
from queue import Empty
from typing import Any, Callable, Optional

import numpy as np

from config.constants import AppMeta, ProcessDefaults, SYCLDefaults
from config.settings import Settings
from core.buffer_manager import BufferManager
from core.event_bus import EventBus
from core.models import StatusEnum
from core.text_dedup import deduplicate_text, remove_chunk_overlap
from core.whisper_backend import WhisperBackend

logger = logging.getLogger(__name__)
EventSink = Callable[[str, Any], None]


class TranscriberThread(threading.Thread):
    def __init__(
        self,
        buffer: BufferManager,
        backend: WhisperBackend,
        settings: Settings,
        *,
        session_id: Optional[str] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        name = f"TranscriberThread-{session_id}" if session_id else "TranscriberThread"
        super().__init__(daemon=True, name=name)
        self._buffer = buffer
        self._backend = backend
        self._settings = settings
        self._session_id = session_id
        self._event_sink = event_sink
        self._stop_event = threading.Event()
        self._current_segment: list[np.ndarray] = []
        self._segment_sample_count = 0
        self._segment_samples = int(
            settings.sample_rate * ProcessDefaults.SEGMENT_LENGTH_S
        )
        self._active_segment_target = self._segment_samples
        # Catch up with already-queued audio without making normal capture wait.
        # Leave room for overlap and one producer chunk below the File window.
        self._catchup_samples = int(
            settings.sample_rate
            * max(
                ProcessDefaults.SEGMENT_LENGTH_S,
                ProcessDefaults.FILE_SEGMENT_LENGTH_S
                - ProcessDefaults.OVERLAP_DURATION_S
                - settings.chunk_ms / 1000,
            )
        )
        self._min_segment_samples = int(
            settings.sample_rate * ProcessDefaults.MIN_SEGMENT_S
        )
        self._overlap_samples = int(
            settings.sample_rate * ProcessDefaults.OVERLAP_DURATION_S
        )
        self._overlap_buffer = np.array([], dtype=np.float32)
        self._last_emitted_text = ""
        self._terminal_error = False

    def _emit(self, event: str, payload: Any = None) -> None:
        if self._event_sink is not None:
            self._event_sink(event, payload)
        else:
            EventBus().emit(event, payload)

    def run(self) -> None:
        self._emit("transcriber_status_changed", StatusEnum.RUNNING.value)
        drained = False
        try:
            drained = self._loop()
        except Exception as exc:
            self._terminal_error = True
            if not self._stop_event.is_set():
                logger.exception("Errore trascrizione live")
                self._emit("transcriber_error", f"Errore trascrizione: {exc}")
                self._emit("transcriber_status_changed", StatusEnum.ERROR.value)
        finally:
            if drained and not self._stop_event.is_set():
                try:
                    self._flush_segment(final=True)
                except Exception as exc:
                    self._terminal_error = True
                    self._persist_recovery_audio()
                    self._emit("transcriber_error", f"Errore flush finale: {exc}")
                    self._emit("transcriber_status_changed", StatusEnum.ERROR.value)
                else:
                    self._emit("transcriber_drained", None)
            elif not drained:
                self._persist_recovery_audio()
            if not self._terminal_error:
                self._emit("transcriber_status_changed", StatusEnum.STOPPED.value)

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> bool:
        while not self._stop_event.is_set():
            try:
                chunk = self._buffer.get(timeout=0.5)
            except Empty:
                if self._buffer.input_closed and self._buffer.is_empty:
                    return True
                self._emit("transcriber_buffer_level", self._buffer.buffer_level)
                continue
            if not self._current_segment:
                available = (
                    int(self._buffer.pending_seconds * self._settings.sample_rate)
                    + chunk.size
                )
                self._active_segment_target = max(
                    self._segment_samples, min(self._catchup_samples, available)
                )
                if self._active_segment_target > self._segment_samples:
                    logger.info(
                        "Recupero Live: %.1f s già in attesa; blocco obiettivo %.1f s",
                        available / self._settings.sample_rate,
                        self._active_segment_target / self._settings.sample_rate,
                    )
            self._current_segment.append(
                np.asarray(chunk, dtype=np.float32).reshape(-1)
            )
            self._segment_sample_count += chunk.shape[0]
            self._emit("transcriber_buffer_level", self._buffer.buffer_level)
            if self._segment_sample_count >= self._active_segment_target:
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
        if self._stop_event.is_set():
            raise RuntimeError("trascrizione interrotta")
        cleaned = remove_chunk_overlap(self._last_emitted_text, text)
        cleaned = deduplicate_text(cleaned)
        if cleaned:
            self._emit("transcriber_new_text", cleaned)
            self._last_emitted_text = (self._last_emitted_text + " " + cleaned).strip()[
                -1200:
            ]
        self._commit_segment(body, final)

    def _commit_segment(self, body: np.ndarray, final: bool) -> None:
        self._current_segment.clear()
        self._segment_sample_count = 0
        if (
            not final
            and self._overlap_samples > 0
            and body.size > self._overlap_samples
        ):
            self._overlap_buffer = body[-self._overlap_samples :].copy()
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
                    wav,
                    language=self._settings.language,
                    prompt=prompt,
                    verbose=False,
                    timeout=SYCLDefaults.LIVE_REQUEST_TIMEOUT_S,
                    vad=self._settings.vad_filter,
                    on_queue_wait=self._on_queue_wait,
                )
                if self._stop_event.is_set():
                    raise RuntimeError("trascrizione interrotta")
                return (
                    result if isinstance(result, str) else str(result.get("text", ""))
                )
            except RuntimeError as exc:
                last = exc
                if self._stop_event.is_set():
                    raise
                if attempt < 2:
                    self._stop_event.wait(ProcessDefaults.TRANSCRIBE_RETRY_DELAY_S)
        raise RuntimeError(f"segmento live non trascritto dopo 3 tentativi: {last}")

    def _on_queue_wait(self, wait_ms: float) -> None:
        logger.debug(
            "Attesa scheduler sessione %s: %.1f ms; audio FIFO %.2f s, %d chunk su disco",
            self._session_id,
            wait_ms,
            self._buffer.pending_seconds,
            self._buffer.spooled_chunks,
        )
        self._emit("transcriber_queue_wait", float(wait_ms))

    def _persist_recovery_audio(self, audio: np.ndarray | None = None) -> None:
        try:
            AppMeta.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            session_part = self._safe_session_component(self._session_id)
            suffix = f"-{session_part}" if session_part else ""
            path = AppMeta.CACHE_DIR / f"recovery-live{suffix}-{time.time_ns()}.wav"
            temporary = path.with_suffix(".wav.tmp")
            parts = (
                [audio]
                if audio is not None
                else [self._overlap_buffer, *self._current_segment]
            )
            written = 0
            with wave.open(str(temporary), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(self._settings.sample_rate)

                def append(part):
                    nonlocal written
                    if part is not None and part.size:
                        output.writeframesraw(
                            (np.clip(part, -1, 1) * 32767).astype("<i2").tobytes()
                        )
                        written += part.size

                for part in parts:
                    append(part)
                if audio is None:
                    while True:
                        try:
                            append(self._buffer.get_nowait())
                        except Empty:
                            break
            if not written:
                temporary.unlink(missing_ok=True)
                return
            with temporary.open("rb") as persisted:
                os.fsync(persisted.fileno())
            os.replace(temporary, path)
            logger.warning("Audio non trascritto salvato per recupero: %s", path)
            self._emit("recovery_audio_saved", str(path))
        except OSError:
            logger.exception("Impossibile salvare recovery audio")
            self._emit(
                "transcriber_error",
                "Impossibile salvare l’audio residuo: verifica lo spazio su disco",
            )

    @staticmethod
    def _safe_session_component(session_id: Optional[str]) -> str:
        if not session_id:
            return ""
        return "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")[:64]

    @staticmethod
    def _numpy_to_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()
        header = struct.pack(
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
            peak = max(peak, self._compute_rms(audio[i : i + win]))
        return peak < ProcessDefaults.SILENCE_RMS_THRESHOLD
