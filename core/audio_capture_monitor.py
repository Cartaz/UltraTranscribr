"""Cattura monitor PipeWire/PulseAudio via callback PortAudio."""
from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

from core.buffer_manager import BufferManager

logger = logging.getLogger(__name__)


def monitor_callback(indata: np.ndarray, frames: int, time_info: object,
                     status: sd.CallbackFlags, *, stop_event: threading.Event,
                     cb_lock: threading.Lock, cb_accumulator: list,
                     buffer: BufferManager, chunk_samples: int) -> None:
    if stop_event.is_set():
        raise sd.CallbackStop
    if status:
        logger.debug("Monitor callback status: %s", status)

    if indata.ndim > 1:
        data = np.mean(indata, axis=1, dtype=np.float32)
    else:
        data = np.asarray(indata, dtype=np.float32).reshape(-1)

    with cb_lock:
        cb_accumulator[0] = np.concatenate((cb_accumulator[0], data))
        chunks: list[np.ndarray] = []
        while cb_accumulator[0].size >= chunk_samples:
            chunks.append(cb_accumulator[0][:chunk_samples].copy())
            cb_accumulator[0] = cb_accumulator[0][chunk_samples:]
    for chunk in chunks:
        buffer.put(chunk)


def monitor_capture_loop(*, stop_event: threading.Event, lock: threading.Lock,
                         cb_lock: threading.Lock, cb_accumulator: list,
                         buffer: BufferManager) -> None:
    while not stop_event.wait(0.25):
        pass
    with cb_lock:
        if cb_accumulator[0].size:
            tail = cb_accumulator[0].copy()
            cb_accumulator[0] = np.array([], dtype=np.float32)
        else:
            tail = None
    if tail is not None:
        buffer.put(tail)
