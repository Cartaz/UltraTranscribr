"""Cattura microfono con resampling streaming stateful."""
from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

from core.audio_resampler import StreamingLinearResampler, WHISPER_SAMPLE_RATE
from core.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


def microphone_capture_loop(*, stream: sd.InputStream, stop_event: threading.Event,
                            lock: threading.Lock, buffer: BufferManager,
                            chunk_samples: int, native_sr: int,
                            needs_resample: bool) -> None:
    overflow = np.array([], dtype=np.float32)
    converter = (
        StreamingLinearResampler(native_sr, WHISPER_SAMPLE_RATE)
        if needs_resample else None
    )

    while not stop_event.is_set():
        try:
            data, overflow_flag = stream.read(1024)
            if overflow_flag:
                logger.warning("Overflow PortAudio durante cattura microfono")
        except (OSError, RuntimeError, sd.PortAudioError) as exc:
            if stop_event.is_set():
                break
            raise RuntimeError(f"Errore lettura stream: {exc}") from exc

        if data.ndim > 1:
            data = np.mean(data, axis=1, dtype=np.float32)
        else:
            data = np.asarray(data, dtype=np.float32).reshape(-1)
        if converter is not None:
            data = converter.process(data)
        if overflow.size:
            data = np.concatenate((overflow, data))
            overflow = np.array([], dtype=np.float32)
        while data.size >= chunk_samples:
            buffer.put(data[:chunk_samples].copy())
            data = data[chunk_samples:]
        if data.size:
            overflow = data.copy()

    if converter is not None:
        tail = converter.flush()
        if tail.size:
            overflow = np.concatenate((overflow, tail)) if overflow.size else tail
    if overflow.size:
        buffer.put(overflow)
