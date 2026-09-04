from __future__ import annotations

import threading
import time
from pathlib import Path

from config.constants import AppMeta
from config.settings import Settings
from core.event_bus import EventBus
from core.meeting_manager import MeetingManager
from core.meeting_store import MeetingStore
from core.transcript_history import TranscriptHistoryStore


class _Controller:
    def __init__(self, history: TranscriptHistoryStore) -> None:
        self.settings = Settings(language="it", model_size="medium")
        self.history = history
        self.backend = object()

    def active_live_count(self) -> int:
        return 0

    def is_file_busy(self) -> bool:
        return False

    def ensure_backend_started(self, **kwargs) -> None:
        del kwargs
        raise AssertionError("Whisper must not start during diarization-only rerun")


class _ReadyModels:
    def status(self) -> dict[str, object]:
        return {"ready": True, "model": "community-1"}

    def ensure_models(self, progress=None) -> dict[str, object]:
        del progress
        return self.status()


class _FailingDiarizer:
    def run(self, path, *, num_speakers, progress=None):
        del path, num_speakers, progress
        raise RuntimeError("forced Community-1 failure")


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_failed_rediarization_keeps_last_good_persisted_review(monkeypatch, tmp_path: Path) -> None:
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)

    history = TranscriptHistoryStore(tmp_path / "transcripts")
    store = MeetingStore(history, tmp_path / "meetings")
    session_id = store.create(
        model="medium",
        language="it",
        source="microphone",
        source_path="Test Mic",
        num_speakers=2,
    )
    history.append_text(session_id, "Testo raw")
    history.append_segments(
        session_id,
        [{"start": 0.0, "end": 1.0, "text": "Testo raw"}],
    )
    audio = recordings / f"{session_id}.flac"
    audio.write_bytes(b"retained audio")
    store.set_recording(
        session_id,
        {
            "path": str(audio),
            "duration_s": 1.0,
            "size_bytes": audio.stat().st_size,
            "sample_rate": 16000,
            "channels": 1,
            "format": "flac",
        },
    )
    original_diarization = [
        {"start": 0.0, "end": 1.0, "speaker_id": "SPEAKER_00"}
    ]
    original_review = [
        {
            "start": 0.0,
            "end": 1.0,
            "raw_text": "Testo raw",
            "text": "Correzione manuale",
            "speaker_id": "SPEAKER_00",
            "uncertain": False,
            "speaker_candidates": ["SPEAKER_00"],
        }
    ]
    store.set_diarization(
        session_id,
        diarization_segments=original_diarization,
        review_segments=original_review,
        num_speakers=2,
    )
    store.set_speaker_name(session_id, "SPEAKER_00", "Marco")
    store.set_status(session_id, "completed", terminal=True)

    controller = _Controller(history)
    manager = MeetingManager.__new__(MeetingManager)
    manager._controller = controller
    manager._inputs = None
    manager.store = store
    manager.models = _ReadyModels()
    manager.diarizer = _FailingDiarizer()
    manager._bus = EventBus()
    manager._lock = threading.RLock()
    manager._runtime = None
    manager._closed = False
    manager._shutdown_event = threading.Event()

    started = manager.rerun_diarization(session_id, num_speakers=4)
    assert started["operation"] == "rediarization"
    _wait_until(lambda: manager.snapshot()["status"] == "error")

    persisted = manager.get(session_id)
    assert persisted is not None
    assert persisted["status"] == "completed"
    assert persisted["segments"] == [
        {"start": 0.0, "end": 1.0, "text": "Testo raw"}
    ]
    assert persisted["meeting"]["num_speakers"] == 2
    assert persisted["meeting"]["diarization_segments"] == original_diarization
    assert persisted["meeting"]["review_segments"] == original_review
    assert persisted["meeting"]["speaker_names"] == {"SPEAKER_00": "Marco"}
