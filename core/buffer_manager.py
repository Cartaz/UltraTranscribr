"""Buffer audio thread-safe con spill su disco per limitare la RAM."""
from __future__ import annotations

import logging
import os
import struct
import tempfile
import threading
import time
from collections import deque
from queue import Empty
from typing import Optional

import numpy as np

from config.constants import ProcessDefaults

logger = logging.getLogger(__name__)


class BufferManager:
    """FIFO audio che conserva tutti i chunk e limita l'uso di RAM.

    Fino a ``max_memory_chunks`` i chunk restano in memoria. Se il consumer
    rimane indietro, i nuovi chunk vengono serializzati in un TemporaryFile;
    finche lo spool non e svuotato tutti i nuovi chunk continuano ad andarvi,
    preservando rigorosamente l'ordine FIFO.
    """

    def __init__(self, warn_threshold: int = 20, level_window_seconds: float = 5.0,
                 max_memory_chunks: int = ProcessDefaults.BUFFER_MAX_MEMORY_CHUNKS) -> None:
        if warn_threshold <= 0:
            raise ValueError("warn_threshold deve essere > 0")
        if max_memory_chunks <= 0:
            raise ValueError("max_memory_chunks deve essere > 0")
        self._warn_threshold = int(warn_threshold)
        self._max_memory_chunks = int(max_memory_chunks)
        self._condition = threading.Condition(threading.RLock())
        self._memory: deque[np.ndarray] = deque()
        self._spool = tempfile.TemporaryFile(prefix="ultratranscribr_buffer_", suffix=".bin")
        self._spool_read_pos = 0
        self._spooled_count = 0
        self._spool_active = False
        self._total_put = 0
        self._total_get = 0
        self._start_time = time.monotonic()
        self._window = float(level_window_seconds)
        self._input_closed = False

    def put(self, chunk: np.ndarray) -> None:
        arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        with self._condition:
            if self._spool_active or len(self._memory) >= self._max_memory_chunks:
                self._write_spooled(arr)
                self._spool_active = True
            else:
                self._memory.append(arr.copy())
            self._total_put += 1
            self._condition.notify()

    def _write_spooled(self, arr: np.ndarray) -> None:
        self._spool.seek(0, os.SEEK_END)
        raw = arr.astype(np.float32, copy=False).tobytes()
        self._spool.write(struct.pack("<Q", arr.size))
        self._spool.write(raw)
        self._spool.flush()
        self._spooled_count += 1

    def _read_spooled(self) -> np.ndarray:
        self._spool.seek(self._spool_read_pos)
        header = self._spool.read(8)
        if len(header) != 8:
            raise RuntimeError("spool audio corrotto: header incompleto")
        count = struct.unpack("<Q", header)[0]
        raw = self._spool.read(count * 4)
        if len(raw) != count * 4:
            raise RuntimeError("spool audio corrotto: payload incompleto")
        self._spool_read_pos = self._spool.tell()
        self._spooled_count -= 1
        arr = np.frombuffer(raw, dtype=np.float32).copy()
        if self._spooled_count == 0:
            self._spool.seek(0)
            self._spool.truncate(0)
            self._spool_read_pos = 0
            self._spool_active = False
        return arr

    def get(self, timeout: Optional[float] = None) -> np.ndarray:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._memory and self._spooled_count == 0:
                if timeout is None:
                    self._condition.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Empty
                    self._condition.wait(remaining)
            if self._memory:
                chunk = self._memory.popleft()
            else:
                chunk = self._read_spooled()
            self._total_get += 1
            return chunk

    def get_nowait(self) -> np.ndarray:
        with self._condition:
            if not self._memory and self._spooled_count == 0:
                raise Empty
            if self._memory:
                chunk = self._memory.popleft()
            else:
                chunk = self._read_spooled()
            self._total_get += 1
            return chunk

    @property
    def qsize(self) -> int:
        with self._condition:
            return len(self._memory) + self._spooled_count

    @property
    def is_empty(self) -> bool:
        return self.qsize == 0

    @property
    def is_buffering(self) -> bool:
        return self.qsize >= self._warn_threshold

    @property
    def buffer_level(self) -> int:
        return int((self.qsize / self._warn_threshold) * 100)

    @property
    def total_put(self) -> int:
        with self._condition:
            return self._total_put

    @property
    def total_get(self) -> int:
        with self._condition:
            return self._total_get

    @property
    def input_closed(self) -> bool:
        with self._condition:
            return self._input_closed

    def close_input(self) -> None:
        with self._condition:
            self._input_closed = True
            self._condition.notify_all()
        logger.info("Input buffer chiuso")

    def reset_input(self) -> None:
        with self._condition:
            self._input_closed = False

    def clear(self, *, reset_stats: bool = True) -> int:
        with self._condition:
            count = len(self._memory) + self._spooled_count
            self._memory.clear()
            self._spool.seek(0)
            self._spool.truncate(0)
            self._spool_read_pos = 0
            self._spooled_count = 0
            self._spool_active = False
            self._input_closed = False
            if reset_stats:
                self._total_put = 0
                self._total_get = 0
                self._start_time = time.monotonic()
            self._condition.notify_all()
            return count

    def task_done(self) -> None:
        return None

    def close(self) -> None:
        try:
            self._spool.close()
        except OSError:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
