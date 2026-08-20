# core/audio_capture_mic.py
"""Logica di cattura audio per lo stream microfono (ALSA diretto).

Contiene il loop di cattura con read() bloccante e resampling usato
da AudioCaptureThread. Separato da audio_capture.py per rispettare
il limite di 300 righe per file.

Functions:
    microphone_capture_loop: Loop cattura microfono con resampling.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from core.audio_resampler import WHISPER_SAMPLE_RATE, resample
from core.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


def microphone_capture_loop(
    *,
    stream: sd.InputStream,
    stop_event: threading.Event,
    lock: threading.Lock,
    buffer: BufferManager,
    chunk_samples: int,
    native_sr: int,
    needs_resample: bool,
) -> None:
    """Loop cattura microfono: read() bloccante con resampling.

    Legge blocchi audio dallo stream con read() bloccante, effettua
    il resampling se necessario (da sample rate nativo a 16 kHz),
    e trasferisce i blocchi al BufferManager.

    Args:
        stream: InputStream sounddevice aperto.
        stop_event: Event per segnalare lo stop.
        lock: Lock per l'aggiornamento errore.
        buffer: BufferManager in cui inserire i blocchi.
        chunk_samples: Numero di campioni per blocco target.
        native_sr: Sample rate nativo del dispositivo.
        needs_resample: True se e necessario il resampling.
    """
    overflow = np.array([], dtype=np.float32)

    while not stop_event.is_set():
        try:
            if needs_resample:
                native_chunk = int(
                    chunk_samples * native_sr / WHISPER_SAMPLE_RATE)
                blocksize = min(1024, native_chunk)
            else:
                blocksize = min(1024, chunk_samples)

            data, _overflow_flag = stream.read(blocksize)
        except (OSError, RuntimeError) as exc:
            # Stream chiuso da stop() o dispositivo rilasciato
            if stop_event.is_set() or stream is None:
                break
            raise RuntimeError(f"Errore lettura stream: {exc}") from exc
        except sd.PortAudioError as exc:
            # Errore ALSA mmap (xrun): non fatale, ritenta
            if stop_event.is_set() or stream is None:
                break
            logger.warning("Errore PortAudio (xrun?): %s", exc)
            stop_event.wait(0.1)
            continue
        except Exception as exc:
            if stop_event.is_set():
                break
            raise RuntimeError(f"Errore lettura stream: {exc}") from exc

        if data.ndim > 1:
            data = data[:, 0]

        # Resampling da sample rate nativo a 16 kHz
        if needs_resample:
            data = resample(data, native_sr, WHISPER_SAMPLE_RATE)

        if overflow.size > 0:
            data = np.concatenate([overflow, data])
            overflow = np.array([], dtype=np.float32)

        while data.size >= chunk_samples:
            chunk = data[:chunk_samples]
            data = data[chunk_samples:]
            buffer.put(chunk)

        if data.size > 0:
            overflow = data

        with lock:
            pass  # Reset errore — lettura riuscita

    # Flush dei campioni rimanenti nell'overflow dopo l'uscita dal loop.
    # Senza questo, fino a chunk_samples-1 campioni (circa 3s di audio
    # a 16kHz/3000ms) venivano silenziosamente scartati alla fine della
    # cattura. Il TranscriberThread accetta segmenti parziali con
    # is_final=True nel flush finale.
    if overflow.size > 0:
        buffer.put(overflow)
