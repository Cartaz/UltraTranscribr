# core/audio_capture_monitor.py
"""Logica di cattura audio per lo stream monitor (Firefox/PulseAudio).

Contiene la callback PortAudio e il loop di cattura monitor usati
da AudioCaptureThread. Separato da audio_capture.py per rispettare
il limite di 300 righe per file.

Functions:
    monitor_callback: Callback PortAudio per stream monitor.
    monitor_capture_loop: Loop cattura monitor che attende stop e flush.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

from core.audio_resampler import WHISPER_SAMPLE_RATE
from core.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


def monitor_callback(
    indata: np.ndarray,
    frames: int,
    time_info: object,
    status: sd.CallbackFlags,
    *,
    stop_event: threading.Event,
    cb_lock: threading.Lock,
    cb_accumulator: list,  # list con un elemento: np.ndarray
    buffer: BufferManager,
    chunk_samples: int,
) -> None:
    """Callback chiamata da PortAudio per gli stream monitor.

    Accumula i campioni ricevuti e li trasferisce al BufferManager
    in blocchi di chunk_samples.  Quando stop_event e attivo,
    solleva CallbackStop per fermare lo stream.

    Args:
        indata: Buffer audio in ingresso (shape: frames x channels).
        frames: Numero di campioni disponibili.
        time_info: Informazioni temporali PortAudio.
        status: Flag di stato PortAudio (xrun, etc.).
        stop_event: Event per segnalare lo stop.
        cb_lock: Lock per l'accumulatore.
        cb_accumulator: Lista con un elemento (array accumulatore).
        buffer: BufferManager in cui inserire i blocchi.
        chunk_samples: Numero di campioni per blocco.
    """
    if stop_event.is_set():
        raise sd.CallbackStop

    if status:
        logger.debug("Monitor callback status: %s", status)

    # Estrai canale mono
    data = indata[:, 0] if indata.ndim > 1 else indata.flatten()

    with cb_lock:
        cb_accumulator[0] = np.concatenate([cb_accumulator[0], data])

        # Estrai blocchi completi dall'accumulatore tenendo il lock
        # il minor tempo possibile. buffer.put() acquisisce il mutex
        # interno della Queue, e tenerlo mentre si detiene cb_lock
        # puo bloccare la callback di PortAudio causando xrun.
        chunks_to_send: list[np.ndarray] = []
        while cb_accumulator[0].size >= chunk_samples:
            chunks_to_send.append(cb_accumulator[0][:chunk_samples].copy())
            cb_accumulator[0] = cb_accumulator[0][chunk_samples:]

    # Invia i chunk al buffer fuori dal lock per evitare xrun
    for chunk in chunks_to_send:
        buffer.put(chunk)


def monitor_capture_loop(
    *,
    stop_event: threading.Event,
    lock: threading.Lock,
    cb_lock: threading.Lock,
    cb_accumulator: list,  # list con un elemento: np.ndarray
    buffer: BufferManager,
) -> None:
    """Loop cattura monitor: attende stop_event, la callback fa il lavoro.

    Lo stream monitor usa una callback PortAudio che accumula i campioni
    e li trasferisce al BufferManager.  Questo loop si limita ad
    attendere il segnale di stop, poi fa il flush dei campioni rimanenti.

    Args:
        stop_event: Event per segnalare lo stop.
        lock: Lock per l'errore.
        cb_lock: Lock per l'accumulatore.
        cb_accumulator: Lista con un elemento (array accumulatore).
        buffer: BufferManager in cui inserire i blocchi finali.
    """
    with lock:
        pass  # Reset errore avvenuto in _open_stream

    # Attendi il segnale di stop (la callback lavora in background)
    while not stop_event.is_set():
        stop_event.wait(timeout=0.5)

    # Flush dei campioni rimanenti nell'accumulatore.
    # NOTA: in precedenza i campioni residui < 2 secondi venivano
    # scartati silenziosamente, causando perdita di audio alla fine
    # della cattura. Ora tutti i campioni vengono trasferiti al
    # buffer indipendentemente dalla durata; il TranscriberThread
    # ha una soglia minima di segmento (2s) ma il flush finale
    # (is_final=True) accetta segmenti di qualsiasi lunghezza.
    with cb_lock:
        if cb_accumulator[0].size > 0:
            buffer.put(cb_accumulator[0].copy())
            cb_accumulator[0] = np.array([], dtype=np.float32)
