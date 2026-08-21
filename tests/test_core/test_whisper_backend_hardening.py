"""Endpoint fallback, timeout and process lifecycle coverage for WhisperBackend."""
from __future__ import annotations

import io
import subprocess
import urllib.error
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.whisper_backend import WhisperBackend


class _Response:
    def __init__(self, payload=b'{"text":"ok"}', status=200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb

    def read(self):
        return self._payload


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://127.0.0.1/test",
        code,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _running_backend(tmp_path) -> WhisperBackend:
    backend = WhisperBackend(Settings(), tmp_path)
    process = MagicMock()
    process.poll.return_value = None
    backend._process = process
    return backend


def test_transcribe_falls_back_to_alternate_endpoint_after_404(monkeypatch, tmp_path) -> None:
    backend = _running_backend(tmp_path)
    backend._api_endpoint = "/inference"
    urlopen = MagicMock(side_effect=[_http_error(404), _Response()])
    monkeypatch.setattr("core.whisper_backend.urllib.request.urlopen", urlopen)

    assert backend.transcribe_audio(b"wav", language="it") == "ok"
    assert backend.api_endpoint == "/v1/audio/transcriptions"
    assert urlopen.call_count == 2
    assert urlopen.call_args_list[0].args[0].full_url.endswith("/inference")
    assert urlopen.call_args_list[1].args[0].full_url.endswith("/v1/audio/transcriptions")


def test_non_404_http_error_does_not_probe_another_endpoint(monkeypatch, tmp_path) -> None:
    backend = _running_backend(tmp_path)
    urlopen = MagicMock(side_effect=_http_error(500, b"server exploded"))
    monkeypatch.setattr("core.whisper_backend.urllib.request.urlopen", urlopen)

    with pytest.raises(RuntimeError, match="HTTP 500") as exc_info:
        backend.transcribe_audio(b"wav")
    assert "server exploded" in str(exc_info.value)
    assert urlopen.call_count == 1


def test_request_timeout_is_forwarded_and_wrapped(monkeypatch, tmp_path) -> None:
    backend = _running_backend(tmp_path)
    urlopen = MagicMock(side_effect=TimeoutError("too slow"))
    monkeypatch.setattr("core.whisper_backend.urllib.request.urlopen", urlopen)

    with pytest.raises(RuntimeError, match="too slow"):
        backend.transcribe_audio(b"wav", timeout=7.5)

    assert urlopen.call_args.kwargs["timeout"] == 7.5


def test_endpoint_detection_accepts_validation_error_as_supported(monkeypatch, tmp_path) -> None:
    backend = WhisperBackend(Settings(), tmp_path)
    urlopen = MagicMock(side_effect=[_http_error(404), _http_error(422)])
    monkeypatch.setattr("core.whisper_backend.urllib.request.urlopen", urlopen)

    backend._detect_api_endpoint()

    assert backend.api_endpoint == "/v1/audio/transcriptions"
    assert urlopen.call_count == 2


def test_cleanup_escalates_from_terminate_to_kill_on_timeout(tmp_path) -> None:
    backend = WhisperBackend(Settings(), tmp_path)
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("whisper-server", 3.0), 0]
    backend._process = process
    handle = MagicMock()
    handle.closed = False
    backend._log_file_handle = handle
    backend._server_vad_enabled = True

    backend._cleanup_process()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
    handle.close.assert_called_once_with()
    assert backend._process is None
    assert backend._log_file_handle is None
    assert backend.server_vad_enabled is False


def test_health_check_reports_early_process_exit_with_log(monkeypatch, tmp_path) -> None:
    backend = WhisperBackend(Settings(), tmp_path)
    process = MagicMock()
    process.poll.return_value = 2
    backend._process = process
    monkeypatch.setattr(backend, "_read_log_tail", lambda chars=2500: "fatal sycl error")

    with pytest.raises(RuntimeError, match="fatal sycl error"):
        backend._wait_for_health()


def test_transcribe_rechecks_process_after_waiting_for_scheduler_lock(tmp_path) -> None:
    backend = _running_backend(tmp_path)
    backend._io_lock.acquire()
    try:
        process = backend._process
        assert process is not None
        process.poll.side_effect = [None, 1]
        # The first is_running check succeeds before queueing, the second one
        # must reject the request after entering the serialized section.
        backend._io_lock.release()
        with pytest.raises(RuntimeError, match="non in esecuzione"):
            backend.transcribe_audio(b"wav")
    finally:
        try:
            backend._io_lock.release()
        except RuntimeError:
            pass
