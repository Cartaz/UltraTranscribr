"""Tests for serialized requests on the shared whisper-server backend."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from config.settings import Settings
from core.whisper_backend import WhisperBackend


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb

    def read(self):
        return b'{"text":"ok"}'


def test_queue_wait_measures_time_blocked_on_shared_inference_lock():
    backend = WhisperBackend(Settings())
    process = MagicMock()
    process.poll.return_value = None
    backend._process = process

    waits = []
    result = []

    # Hold the scheduler lock before starting the request. This makes the
    # measured wait deterministic without depending on thread scheduling races.
    backend._io_lock.acquire()
    try:
        with patch("core.whisper_backend.urllib.request.urlopen", return_value=_Response()):
            worker = threading.Thread(
                target=lambda: result.append(
                    backend.transcribe_audio(
                        b"wav",
                        on_queue_wait=lambda value: waits.append(value),
                    )
                )
            )
            worker.start()
            time.sleep(0.04)
            backend._io_lock.release()
            worker.join(timeout=2.0)
    finally:
        # If the assertion path fails before release, do not poison the test process.
        try:
            backend._io_lock.release()
        except RuntimeError:
            pass

    assert result == ["ok"]
    assert len(waits) == 1
    assert waits[0] >= 20.0
