# core/buffer_manager.py
"""Buffer audio thread-safe con monitoraggio del livello.

Usa una coda illimitata (queue.Queue) in modo che i blocchi audio
non vengano mai scartati. Il consumer recupera gradualmente se
la CPU e piu lenta del real-time.

Classes:
    BufferManager: Buffer audio con monitoraggio del livello.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from queue import Empty, Queue
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class BufferManager:
    """Buffer audio thread-safe con monitoraggio e segnalazione backpressure.

    La coda e illimitata (maxsize=0) per non perdere audio sotto carico.
    Il livello del buffer e calcolato da una finestra scorrevole dei
    tassi di put/get recenti.

    Args:
        warn_threshold: Soglia blocchi in coda per stato BUFFERING.
        level_window_seconds: Finestra temporale per il calcolo del tasso.
    """

    def __init__(
        self,
        warn_threshold: int = 20,
        level_window_seconds: float = 5.0,
    ) -> None:
        self._queue: Queue[np.ndarray] = Queue(maxsize=0)
        self._warn_threshold = warn_threshold
        self._lock = threading.Lock()
        self._total_put = 0
        self._total_get = 0
        self._start_time = time.monotonic()
        self._put_times: deque[float] = deque()
        self._get_times: deque[float] = deque()
        self._window = level_window_seconds
        self._input_closed = False

    # ── API Producer ────────────────────────────────────────────────

    def put(self, chunk: np.ndarray) -> None:
        """Inserisce un blocco audio nel buffer.

        Chiamato da AudioCaptureThread (producer).

        Args:
            chunk: Array numpy di campioni audio float32.
        """
        self._queue.put(chunk)
        now = time.monotonic()
        with self._lock:
            self._total_put += 1
            self._put_times.append(now)
        self._prune_times(now)

    # ── API Consumer ────────────────────────────────────────────────

    def get(self, timeout: Optional[float] = None) -> np.ndarray:
        """Blocca fino a quando un blocco audio e disponibile.

        Chiamato da TranscriberThread (consumer).

        Args:
            timeout: Tempo massimo di attesa in secondi.

        Returns:
            Array numpy di campioni audio float32.

        Raises:
            queue.Empty: Se il timeout scade senza dati disponibili.
        """
        chunk = self._queue.get(timeout=timeout)
        now = time.monotonic()
        with self._lock:
            self._total_get += 1
            self._get_times.append(now)
        return chunk

    def get_nowait(self) -> np.ndarray:
        """Prelievo non bloccante.

        Returns:
            Array numpy di campioni audio float32.

        Raises:
            queue.Empty: Se il buffer e vuoto.
        """
        chunk = self._queue.get_nowait()
        now = time.monotonic()
        with self._lock:
            self._total_get += 1
            self._get_times.append(now)
        return chunk

    # ── API Monitoraggio ────────────────────────────────────────────

    @property
    def qsize(self) -> int:
        """Numero corrente di blocchi nella coda.

        Returns:
            Dimensione corrente della coda.
        """
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        """Indica se il buffer e vuoto.

        Returns:
            True se la coda e vuota.
        """
        return self._queue.empty()

    @property
    def is_buffering(self) -> bool:
        """Indica se la profondita della coda supera la soglia di avviso.

        Returns:
            True se il buffer e in stato di buffering.
        """
        return self.qsize >= self._warn_threshold

    @property
    def buffer_level(self) -> int:
        """Percentuale di riempimento stimata del buffer (0-100).

        Returns:
            Percentuale di riempimento, clampata a [0, 100].
        """
        with self._lock:
            depth = self.qsize
            if self._warn_threshold <= 0:
                return 0 if depth == 0 else 100
            pct = int((depth / self._warn_threshold) * 100)
            return min(pct, 100)

    @property
    def total_put(self) -> int:
        """Totale blocchi inseriti dall'inizio.

        Returns:
            Numero totale di put.
        """
        with self._lock:
            return self._total_put

    @property
    def total_get(self) -> int:
        """Totale blocchi prelevati dall'inizio.

        Returns:
            Numero totale di get.
        """
        with self._lock:
            return self._total_get

    # ── Segnale chiusura input ────────────────────────────────────────

    @property
    def input_closed(self) -> bool:
        """Indica se il producer ha smesso di inserire dati.

        Quando True, il consumer sa che nessun nuovo dato verra inserito
        e puo fermarsi dopo aver svuotato il buffer.

        Returns:
            True se il producer ha chiuso l'input.
        """
        with self._lock:
            return self._input_closed

    def close_input(self) -> None:
        """Segnala che nessun nuovo dato verra inserito nel buffer.

        Chiamato quando il producer (AudioCaptureThread) viene fermato
        ma il consumer (TranscriberThread) deve ancora svuotare il buffer.
        """
        with self._lock:
            self._input_closed = True
        logger.info("Input del buffer chiuso — il consumer svuotera i dati residui")

    def reset_input(self) -> None:
        """Ripristina lo stato di input per una nuova sessione.

        Chiamato all'avvio di una nuova sessione di cattura.
        """
        with self._lock:
            self._input_closed = False

    # ── Controllo ───────────────────────────────────────────────────

    def clear(self) -> int:
        """Scarta tutti i blocchi nel buffer e resetta lo stato di input.

        Returns:
            Numero di blocchi scartati.
        """
        with self._lock:
            self._input_closed = False
        count = 0
        while True:
            try:
                self._queue.get_nowait()
                count += 1
            except Empty:
                break
        return count

    def task_done(self) -> None:
        """Segna un blocco come processato (per semantica queue join)."""
        self._queue.task_done()

    # ── Interno ─────────────────────────────────────────────────────

    def _prune_times(self, now: float) -> None:
        """Rimuove timestamp fuori dalla finestra scorrevole.

        Args:
            now: Timestamp corrente monotono.
        """
        cutoff = now - self._window
        with self._lock:
            while self._put_times and self._put_times[0] < cutoff:
                self._put_times.popleft()
            while self._get_times and self._get_times[0] < cutoff:
                self._get_times.popleft()
