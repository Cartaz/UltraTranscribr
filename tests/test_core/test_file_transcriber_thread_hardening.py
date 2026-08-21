"""Dedicated conversion, cancellation and retry coverage for FileTranscriberThread."""
from __future__ import annotations

import io
import subprocess
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from core.file_transcriber import FileTranscriberThread
from core.models import StatusEnum


def _worker(backend=None) -> FileTranscriberThread:
    return FileTranscriberThread(
        "input.wav",
        backend or MagicMock(),
        Settings(language="it"),
        language="it",
    )


def test_file_chunk_retries_twice_then_succeeds(monkeypatch) -> None:
    backend = MagicMock()
    backend.transcribe_audio.side_effect = [
        RuntimeError("temporary-1"),
        RuntimeError("temporary-2"),
        {"text": "ok"},
    ]
    worker = _worker(backend)
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: False)

    assert worker._request_chunk(b"wav", "prompt") == "ok"
    assert backend.transcribe_audio.call_count == 3


def test_file_chunk_raises_after_three_failures(monkeypatch) -> None:
    backend = MagicMock()
    backend.transcribe_audio.side_effect = RuntimeError("backend down")
    worker = _worker(backend)
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: False)

    with pytest.raises(RuntimeError, match="chunk file fallito dopo 3 tentativi"):
        worker._request_chunk(b"wav", None)
    assert backend.transcribe_audio.call_count == 3


def test_file_chunk_cancelled_before_request_never_calls_backend() -> None:
    backend = MagicMock()
    worker = _worker(backend)
    worker.stop()

    assert worker._request_chunk(b"wav", None) == ""
    backend.transcribe_audio.assert_not_called()


class _ConversionProcess:
    def __init__(self, *, returncode=None, stderr=b"") -> None:
        self.returncode = returncode
        self.stderr = io.BytesIO(stderr)
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def test_stop_terminates_active_ffmpeg_conversion() -> None:
    worker = _worker()
    proc = _ConversionProcess(returncode=None)
    worker._conversion_process = proc

    worker.stop()

    assert worker._stop_event.is_set()
    assert proc.terminated
    assert worker._conversion_process is proc


def test_conversion_cancel_terminates_process_and_removes_temp(monkeypatch, tmp_path) -> None:
    worker = _worker()
    proc = _ConversionProcess(returncode=None)
    temp_dir = tmp_path / "pcm"
    temp_dir.mkdir()
    monkeypatch.setattr("core.file_transcriber.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("core.file_transcriber.tempfile.mkdtemp", lambda prefix: str(temp_dir))
    monkeypatch.setattr("core.file_transcriber.subprocess.Popen", lambda *a, **k: proc)
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: True)

    with pytest.raises(RuntimeError, match="conversione audio interrotta"):
        worker._convert_to_pcm_wav("input.mp3")

    assert proc.terminated
    assert not temp_dir.exists()
    assert worker._conversion_process is None


def test_ffmpeg_failure_surfaces_stderr_and_cleans_temp(monkeypatch, tmp_path) -> None:
    worker = _worker()
    proc = _ConversionProcess(returncode=1, stderr=b"unsupported codec")
    temp_dir = tmp_path / "pcm-fail"
    temp_dir.mkdir()
    monkeypatch.setattr("core.file_transcriber.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("core.file_transcriber.tempfile.mkdtemp", lambda prefix: str(temp_dir))
    monkeypatch.setattr("core.file_transcriber.subprocess.Popen", lambda *a, **k: proc)

    with pytest.raises(RuntimeError, match="unsupported codec"):
        worker._convert_to_pcm_wav("input.xyz")

    assert not temp_dir.exists()
    assert worker._conversion_process is None


def test_run_emits_stopped_when_cancelled_mid_pipeline(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    class FakeBus:
        def emit(self, name, payload=None):
            events.append((name, payload))

    worker = _worker()
    monkeypatch.setattr("core.file_transcriber.EventBus", lambda: FakeBus())
    monkeypatch.setattr(
        worker,
        "_transcribe_progressively",
        lambda source, start_pct: worker.stop(),
    )
    monkeypatch.setattr(worker, "_cleanup", lambda: None)

    worker.run()

    assert ("file_transcriber_status_changed", StatusEnum.RUNNING.value) in events
    assert ("file_transcriber_status_changed", StatusEnum.STOPPED.value) in events
    assert not any(name == "file_transcriber_completed" for name, _ in events)
