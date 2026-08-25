import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from config.constants import AppMeta
from config.settings import Settings
import core.meeting_manager as meeting_module
from core.meeting_manager import MeetingManager
from core.transcript_history import TranscriptHistoryStore


class _Backend:
    def __init__(self) -> None:
        self.aborts = 0

    def abort_active_request(self) -> None:
        self.aborts += 1


class _Controller:
    def __init__(self, root: Path) -> None:
        self.settings = Settings(language="it", model_size="medium")
        self.history = TranscriptHistoryStore(root / "transcripts")
        self.backend = _Backend()
        self.live_count = 0
        self.file_busy = False
        self.backend_starts = 0

    def active_live_count(self) -> int:
        return self.live_count

    def is_file_busy(self) -> bool:
        return self.file_busy

    def ensure_backend_started(self, **kwargs) -> None:
        del kwargs
        self.backend_starts += 1


class _FakeCapture:
    def __init__(self, buffer, settings, device, source, *, session_id, event_sink, sample_sink) -> None:
        del buffer, settings, source, session_id, event_sink
        self.device = device
        self.sample_sink = sample_sink
        self.alive = False

    def start(self) -> None:
        self.alive = True
        # Half a second of deterministic normalized microphone audio.
        self.sample_sink(np.linspace(-0.1, 0.1, 8000, dtype=np.float32))

    def stop(self) -> None:
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        del timeout
        self.alive = False


class _FakeFileWorker:
    def __init__(self, path, backend, settings, *, language, event_sink, thread_name) -> None:
        del path, backend, settings, language, thread_name
        self.event_sink = event_sink
        self.alive = False

    def start(self) -> None:
        self.alive = True
        self.event_sink("file_transcriber_new_text", "Ciao a tutti")
        self.event_sink(
            "file_transcriber_segments",
            [{"start": 0.0, "end": 0.5, "text": "Ciao a tutti"}],
        )
        self.event_sink("file_transcriber_progress", 100)
        self.alive = False

    def join(self, timeout=None) -> None:
        del timeout

    def stop(self) -> None:
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive


class _Models:
    def status(self):
        return {"ready": True, "segmentation": "seg.onnx", "embedding": "emb.onnx"}

    def ensure_models(self, progress=None):
        if progress:
            progress("segmentation", 100)
        return self.status()


class _Diarizer:
    def run(self, path, *, num_speakers, progress=None):
        del path, num_speakers
        if progress:
            progress(100)
        return [{"start": 0.0, "end": 0.5, "speaker_id": "SPEAKER_00"}]


def _manager(monkeypatch, tmp_path: Path) -> tuple[_Controller, MeetingManager]:
    recordings = tmp_path / "recordings"
    data = tmp_path / "data"
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(AppMeta, "DATA_DIR", data)
    monkeypatch.setattr(meeting_module, "AudioCaptureThread", _FakeCapture)
    monkeypatch.setattr(meeting_module, "FileTranscriberThread", _FakeFileWorker)
    controller = _Controller(tmp_path)
    manager = MeetingManager(controller)
    manager.models = _Models()
    manager.diarizer = _Diarizer()
    return controller, manager


def test_meeting_start_finish_processes_to_reviewable_session(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)

    started = manager.start(microphone="Test Mic", language="it", num_speakers=1)
    assert started["status"] == "recording"

    finishing = manager.finish()
    assert finishing["status"] == "transcribing"
    runtime = manager._runtime
    assert runtime is not None and runtime.processing_thread is not None
    runtime.processing_thread.join(timeout=2.0)

    snapshot = manager.snapshot()
    assert snapshot["status"] == "completed"
    assert controller.backend_starts == 1
    combined = manager.get(started["id"])
    assert combined is not None
    assert combined["kind"] == "meeting"
    assert combined["text"] == "Ciao a tutti"
    assert combined["segments"] == [{"start": 0.0, "end": 0.5, "text": "Ciao a tutti"}]
    review = combined["meeting"]["review_segments"]
    assert review[0]["speaker_id"] == "SPEAKER_00"
    assert review[0]["raw_text"] == "Ciao a tutti"
    assert Path(combined["meeting"]["recording"]["path"]).is_file()


def test_meeting_is_exclusive_with_live_and_file(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)
    controller.live_count = 1
    try:
        manager.start(microphone="Test Mic")
    except RuntimeError as exc:
        assert "Live/File" in str(exc)
    else:
        raise AssertionError("Meeting must reject active Live")

    controller.live_count = 0
    controller.file_busy = True
    try:
        manager.start(microphone="Test Mic")
    except RuntimeError as exc:
        assert "Live/File" in str(exc)
    else:
        raise AssertionError("Meeting must reject active File")


def test_shutdown_during_recording_preserves_audio_and_marks_interrupted(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    started = manager.start(microphone="Test Mic")

    manager.shutdown()

    combined = manager.get(started["id"])
    assert combined is not None
    assert combined["status"] == "interrupted"
    recording = combined["meeting"]["recording"]
    assert recording["path"].endswith(".flac")
    assert Path(recording["path"]).is_file()


def test_orphan_recovery_does_not_block_manager_construction(monkeypatch, tmp_path: Path) -> None:
    recordings = tmp_path / "recordings"
    data = tmp_path / "data"
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(AppMeta, "DATA_DIR", data)
    controller = _Controller(tmp_path)

    entered = threading.Event()
    release = threading.Event()

    def slow_recovery(cls, root=None):
        del cls, root
        entered.set()
        release.wait(timeout=2.0)
        return []

    monkeypatch.setattr(
        meeting_module.MicrophoneRecorder,
        "recover_orphaned",
        classmethod(slow_recovery),
    )

    manager = MeetingManager(controller)
    assert entered.wait(timeout=1.0)
    # Construction returned while the recovery worker is intentionally blocked.
    assert manager._recovery_thread.is_alive()

    release.set()
    manager._recovery_thread.join(timeout=1.0)
    assert not manager._recovery_thread.is_alive()
