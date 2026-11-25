"""Dedicated retry, drain and recovery coverage for TranscriberThread."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from config.settings import Settings
from core.buffer_manager import BufferManager
from core.transcriber import TranscriberThread


def _worker(*, backend=None, event_sink=None):
    buffer = BufferManager(warn_threshold=2, max_memory_chunks=2)
    worker = TranscriberThread(
        buffer,
        backend or MagicMock(),
        Settings(language="it"),
        session_id="phase7/session unsafe",
        event_sink=event_sink,
    )
    return worker, buffer


def test_live_request_retries_twice_then_succeeds(monkeypatch) -> None:
    backend = MagicMock()
    backend.transcribe_audio.side_effect = [
        RuntimeError("temporary-1"),
        RuntimeError("temporary-2"),
        "testo finale",
    ]
    worker, buffer = _worker(backend=backend)
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: False)

    audio = np.full(32000, 0.1, dtype=np.float32)
    try:
        assert worker._transcribe_with_retry(audio) == "testo finale"
        assert backend.transcribe_audio.call_count == 3
    finally:
        buffer.close()


def test_live_request_persists_recovery_after_three_failures(monkeypatch) -> None:
    backend = MagicMock()
    backend.transcribe_audio.side_effect = RuntimeError("backend down")
    worker, buffer = _worker(backend=backend)
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: False)
    persist = MagicMock()
    monkeypatch.setattr(worker, "_persist_recovery_audio", persist)

    audio = np.full(32000, 0.1, dtype=np.float32)
    try:
        worker._current_segment = [audio]

        def fail_loop():
            worker._transcribe_with_retry(audio)

        monkeypatch.setattr(worker, "_loop", fail_loop)
        worker.run()
        assert backend.transcribe_audio.call_count == 3
        persist.assert_called_once_with()
    finally:
        buffer.close()


def test_live_drain_flushes_pending_segment_then_emits_drained(monkeypatch) -> None:
    backend = MagicMock()
    backend.transcribe_audio.return_value = "ciao dal drain"
    events: list[tuple[str, object]] = []
    worker, buffer = _worker(
        backend=backend,
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    audio = np.full(32000, 0.1, dtype=np.float32)
    worker._current_segment = [audio]
    worker._segment_sample_count = audio.size
    monkeypatch.setattr(worker, "_loop", lambda: True)

    try:
        worker.run()
        names = [name for name, _ in events]
        assert names[0] == "transcriber_status_changed"
        assert ("transcriber_new_text", "ciao dal drain") in events
        assert "transcriber_drained" in names
        assert names[-1] == "transcriber_status_changed"
        assert worker._current_segment == []
        backend.transcribe_audio.assert_called_once()
    finally:
        buffer.close()


def test_live_stop_with_pending_segment_saves_recovery(monkeypatch) -> None:
    worker, buffer = _worker()
    audio = np.full(16000, 0.1, dtype=np.float32)
    worker._current_segment = [audio]
    worker._segment_sample_count = audio.size
    persist = MagicMock()
    monkeypatch.setattr(worker, "_persist_recovery_audio", persist)

    try:
        worker.stop()
        worker.run()
        persist.assert_called_once_with()
    finally:
        buffer.close()


def test_recovery_filename_sanitizes_session_id() -> None:
    assert (
        TranscriberThread._safe_session_component("../session: one/../../two")
        == "sessiononetwo"
    )


def _recovery_files(cache_dir):
    return sorted(path.name for path in cache_dir.glob("recovery-live*"))


def test_stop_after_transcribed_audio_does_not_save_overlap_only_recovery(
    tmp_path, monkeypatch
) -> None:
    from config.constants import AppMeta

    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path)
    events = []
    worker, buffer = _worker(event_sink=lambda event, payload: events.append(event))
    worker._overlap_buffer = np.full(32000, 0.1, dtype=np.float32)
    try:
        worker.stop()
        worker.run()
    finally:
        buffer.close()

    assert _recovery_files(tmp_path) == []
    assert "recovery_audio_saved" not in events


def test_stop_with_untranscribed_audio_keeps_overlap_as_context(
    tmp_path, monkeypatch
) -> None:
    import wave

    from config.constants import AppMeta

    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path)
    worker, buffer = _worker()
    worker._overlap_buffer = np.full(320, 0.1, dtype=np.float32)
    worker._current_segment = [np.full(1600, 0.1, dtype=np.float32)]
    try:
        worker.stop()
        worker.run()
    finally:
        buffer.close()

    files = list(tmp_path.glob("recovery-live*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0])) as saved:
        assert saved.getnframes() == 1920
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_recovery_write_removes_partial_temporary(tmp_path, monkeypatch) -> None:
    import os

    from config.constants import AppMeta

    monkeypatch.setattr(AppMeta, "CACHE_DIR", tmp_path)
    events = []
    worker, buffer = _worker(event_sink=lambda event, payload: events.append(event))
    worker._current_segment = [np.full(1600, 0.1, dtype=np.float32)]

    def disk_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_full)
    try:
        worker._persist_recovery_audio()
    finally:
        buffer.close()

    assert list(tmp_path.iterdir()) == []
    assert "transcriber_error" in events
