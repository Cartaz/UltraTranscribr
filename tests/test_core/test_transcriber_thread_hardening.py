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
        with pytest.raises(RuntimeError, match="dopo 3 tentativi"):
            worker._transcribe_with_retry(audio)
        assert backend.transcribe_audio.call_count == 3
        persist.assert_called_once()
        np.testing.assert_array_equal(persist.call_args.args[0], audio)
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
