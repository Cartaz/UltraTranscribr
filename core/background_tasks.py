"""Owned background-thread lifecycle for bounded application shutdown."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class BackgroundTaskGroup:
    """Own short-lived daemon threads behind one small lifecycle contract.

    The group prevents new work after ``close()``, tracks every started thread,
    removes completed work automatically, and performs one bounded join during
    shutdown. Python cannot forcibly cancel arbitrary threads, so callers that
    run long operations must still make those operations cooperatively
    stoppable; survivors are reported explicitly instead of being forgotten.
    """

    def __init__(self, prefix: str, *, join_timeout: float = 10.0) -> None:
        self._prefix = str(prefix)
        self._join_timeout = max(0.0, float(join_timeout))
        self._lock = threading.RLock()
        self._threads: set[threading.Thread] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for thread in self._threads if thread.is_alive())

    def start(self, name: str, target: Callable[[], None]) -> threading.Thread:
        """Start and own one daemon task, rejecting work after shutdown begins."""

        def run() -> None:
            try:
                target()
            finally:
                current = threading.current_thread()
                with self._lock:
                    self._threads.discard(current)

        thread = threading.Thread(
            target=run,
            daemon=True,
            name=f"{self._prefix}-{name}",
        )
        with self._lock:
            if self._closed:
                raise RuntimeError(f"task group {self._prefix} chiuso")
            self._threads.add(thread)
        thread.start()
        return thread

    def close(self) -> list[str]:
        """Stop accepting work and wait a bounded total time for owned tasks."""
        with self._lock:
            self._closed = True
            threads = list(self._threads)

        deadline = time.monotonic() + self._join_timeout
        current = threading.current_thread()
        for thread in threads:
            if thread is current or not thread.is_alive():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

        with self._lock:
            survivors = [
                thread.name
                for thread in self._threads
                if thread is not current and thread.is_alive()
            ]
        if survivors:
            logger.warning(
                "Task ancora attivi dopo shutdown bounded di %s: %s",
                self._prefix,
                ", ".join(sorted(survivors)),
            )
        return survivors
