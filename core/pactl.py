"""Managed ``pactl`` command execution with deterministic shutdown.

The application talks to PipeWire/PulseAudio through short-lived ``pactl``
processes. This module owns those child processes explicitly so shutdown can
terminate every in-flight command instead of relying on daemon-thread teardown.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class PactlRunner:
    """Run ``pactl`` commands while owning every child process lifetime."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: set[subprocess.Popen[str]] = set()
        self._closed = False

    def run(self, args: list[str], *, timeout: float = 10.0) -> Optional[str]:
        """Return stdout on success, otherwise ``None``.

        No shell is involved. Timeout and shutdown both terminate the process,
        wait for a bounded grace period, then escalate to ``kill`` if needed.
        """
        with self._lock:
            if self._closed:
                return None
            try:
                process = subprocess.Popen(
                    ["pactl", *args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except FileNotFoundError as exc:
                logger.debug("pactl non disponibile (%s): %s", " ".join(args), exc)
                return None
            self._processes.add(process)

        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.debug("pactl timeout (%s)", " ".join(args))
                self._stop_process(process)
                return None

            if process.returncode != 0:
                logger.debug(
                    "pactl %s fallito (%d): %s",
                    " ".join(args),
                    process.returncode,
                    stderr.strip(),
                )
                return None
            return stdout.strip()
        finally:
            with self._lock:
                self._processes.discard(process)

    def cancel_all(self) -> None:
        """Terminate all currently running commands without closing the runner."""
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self._stop_process(process)

    def close(self) -> None:
        """Reject new commands and synchronously reap every active child."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            self._stop_process(process)

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        """Stop and reap one child without competing with ``communicate()``."""
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=0.25)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            logger.warning("Impossibile reap rapido di pactl pid=%s", process.pid)
