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


def _running_backend() -> WhisperBackend:
    backend = WhisperBackend(Settings())
    process = MagicMock()
    process.poll.return_value = None
    backend._process = process
    return backend


def test_queue_wait_measures_time_blocked_on_shared_inference_lock():
    backend = _running_backend()
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


def test_backend_shutdown_releases_queued_request_without_deadlock():
    backend = _running_backend()
    first_inside_request = threading.Event()
    release_first = threading.Event()
    results: list[str] = []
    errors: list[str] = []

    def blocking_urlopen(*_args, **_kwargs):
        first_inside_request.set()
        assert release_first.wait(timeout=2.0)
        return _Response()

    def request(label: str) -> None:
        try:
            backend.transcribe_audio(b"wav")
            results.append(label)
        except RuntimeError as exc:
            errors.append(f"{label}:{exc}")

    with patch("core.whisper_backend.urllib.request.urlopen", side_effect=blocking_urlopen):
        first = threading.Thread(target=request, args=("first",))
        second = threading.Thread(target=request, args=("second",))
        first.start()
        assert first_inside_request.wait(timeout=1.0)
        second.start()
        time.sleep(0.03)

        # Lifecycle shutdown does not wait for the inference scheduler lock.
        # The queued request must observe the stopped backend when it reaches
        # the lock rather than entering a second HTTP request.
        backend.stop()
        release_first.set()
        first.join(timeout=2.0)
        second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results == ["first"]
    assert len(errors) == 1
    assert errors[0].startswith("second:whisper-server non in esecuzione")
