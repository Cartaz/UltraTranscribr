from contextlib import contextmanager
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from config.constants import AppMeta
from config.settings import Settings
from core.audio_inputs import AudioInputResolver
import core.meeting_capture as capture_module
import core.meeting_manager as meeting_module
from core.meeting_manager import MeetingManager
from core.speaker_diarization import DiarizationResult
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

    @contextmanager
    def meeting_engine_session(self):
        self.backend.stop()
        yield

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
        # Half a second of deterministic normalized audio per source.
        amplitude = 0.1 if "mic" in str(self.device).lower() else 0.05
        self.sample_sink(np.linspace(-amplitude, amplitude, 8000, dtype=np.float32))

    def stop(self) -> None:
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        del timeout
        self.alive = False


class _BlockingCapture(_FakeCapture):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.join_entered = threading.Event()
        self.release_join = threading.Event()

    def stop(self) -> None:
        # Model a capture backend that needs time to leave its native read.
        return

    def join(self, timeout=None) -> None:
        self.join_entered.set()
        self.release_join.wait(timeout=timeout or 1.0)
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
        return {"ready": True, "model": "community-1"}

    def ensure_models(self, progress=None):
        if progress:
            progress("community-1", 100)
        return self.status()


class _Diarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def run(self, path, *, num_speakers, progress=None):
        self.calls.append((str(path), int(num_speakers)))
        if progress:
            progress(100)
        timeline = [{"start": 0.0, "end": 0.5, "speaker_id": "SPEAKER_00"}]
        return DiarizationResult(
            exclusive_segments=timeline,
            speaker_segments=[dict(item) for item in timeline],
        )


def _manager(
    monkeypatch,
    tmp_path: Path,
    *,
    capture_cls=_FakeCapture,
) -> tuple[_Controller, MeetingManager]:
    recordings = tmp_path / "recordings"
    data = tmp_path / "data"
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(AppMeta, "DATA_DIR", data)
    monkeypatch.setattr(capture_module, "AudioCaptureThread", capture_cls)
    monkeypatch.setattr(meeting_module, "FileTranscriberThread", _FakeFileWorker)
    controller = _Controller(tmp_path)
    resolver = AudioInputResolver(
        router=type("Router", (), {})(),
        sink_resolver=lambda selected, source: selected or f"{source}-auto",
    )
    manager = MeetingManager(controller, resolver)
    manager.models = _Models()
    manager.diarizer = _Diarizer()
    return controller, manager


def test_english_preparation_owns_busy_state_and_can_be_cancelled(monkeypatch, tmp_path):
    from types import SimpleNamespace

    _controller, manager = _manager(monkeypatch, tmp_path)
    manager.english_models = SimpleNamespace(
        dependencies=lambda: {}, missing=lambda: [], models={}, root=tmp_path
    )
    manager.english_diarization_models = SimpleNamespace(
        root=tmp_path, status=lambda: {"ready": True}
    )

    class Preparation:
        def __init__(self, *args, **kwargs):
            assert kwargs["prepare_models_only"] is True
            self.alive = False
        def start(self):
            self.alive = True
        def is_alive(self):
            return self.alive
        def stop(self):
            self.alive = False
        def join(self, timeout=None):
            pass

    monkeypatch.setattr(meeting_module, "EnglishMeetingThread", Preparation)
    try:
        assert manager.prepare_english_models()["busy"]
        assert manager.is_busy()
        first = manager._english_preparation
        manager.prepare_english_models()
        assert manager._english_preparation is first
        assert manager.cancel_english_preparation()["ready"]
        assert not manager.is_busy()
        assert not first.is_alive()
    finally:
        manager.shutdown()


def _single_microphone() -> list[dict[str, object]]:
    return [{"source": "microphone", "selected_input": "Test Mic"}]


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def _completed_meeting(
    manager: MeetingManager,
    *,
    num_speakers: int = 1,
) -> str:
    started = manager.start_realtime(
        _single_microphone(),
        language="it",
        num_speakers=num_speakers,
     pipeline="whisper")
    manager.finish()
    _wait_until(lambda: manager.snapshot()["status"] == "completed")
    return str(started["id"])


def test_meeting_exposes_only_canonical_start_entrypoints(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    assert not hasattr(manager, "start")
    assert callable(manager.start_realtime)
    assert callable(manager.start_file)
    assert callable(manager.rerun_diarization)


def test_english_pipeline_requires_explicit_english_language(monkeypatch, tmp_path):
    _, manager = _manager(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="lingua inglese"):
        manager.start_realtime(_single_microphone(), language="it", pipeline="english_qwen")
    assert manager.snapshot() is None
    manager.shutdown()


@pytest.mark.parametrize("pipeline,language", [("english_qwen", "en"), ("qwen_meeting", "en"), (None, "it")])
def test_qwen_meeting_and_voice_rerun_preserve_provenance_and_edits(monkeypatch, tmp_path, pipeline, language):
    from types import SimpleNamespace

    controller, manager = _manager(monkeypatch, tmp_path)
    manager.english_models = SimpleNamespace(root=tmp_path / "english", dependencies=lambda: {}, missing=lambda: [])
    manager.models.root = tmp_path / "diarization"
    manager.english_diarization_models = manager.models
    stopped, released, operations = [], [], []
    monkeypatch.setattr(controller.backend, "stop", lambda: stopped.append(True), raising=False)
    monkeypatch.setattr(manager.diarizer, "release", lambda: released.append(True), raising=False)

    class EnglishWorker(_FakeFileWorker):
        def __init__(self, path, *, event_sink, diarization_only=False, **kwargs):
            self.event_sink = event_sink
            self.alive = False
            self.diarization_only = diarization_only
            operations.append(diarization_only)
            self.provenance = {"pipeline": "verified-fixture", "source_audit": {"complete_audio_coverage": True}}
            self.exclusive_segments = [{"start": 0, "end": .5, "speaker_id": "SPEAKER_00"}]
            self.speaker_segments = list(self.exclusive_segments)
            self._terminal_state = "completed"

        def start(self):
            if not self.diarization_only:
                self.event_sink("file_transcriber_new_text", "One two")
                self.event_sink("file_transcriber_segments", [{"start": 0, "end": .5, "text": "One two"}])
            self.event_sink("file_transcriber_progress", 100)

    monkeypatch.setattr(meeting_module, "EnglishMeetingThread", EnglishWorker)
    started = manager.start_realtime(_single_microphone(), language=language,
                                     **({"pipeline": pipeline} if pipeline else {}))
    manager.finish()
    _wait_until(lambda: manager.snapshot()["status"] == "completed")
    session = started["id"]
    saved = manager.get(session)
    assert saved["text"] == "One two"
    assert saved["meeting"]["processing_pipeline"]["id"] == (pipeline or "qwen_meeting")
    assert saved["meeting"]["processing_pipeline"]["provenance"]["pipeline"] == "verified-fixture"
    assert controller.backend_starts == 0
    assert manager.diarizer.calls == []
    manager.store.edit_review_segment(session, 0, "Edited words")
    manager.store.set_speaker_name(session, "SPEAKER_00", "Alice")
    manager.rerun_diarization(session, num_speakers=1)
    _wait_until(lambda: not manager.is_busy())
    saved = manager.get(session)
    assert saved["text"] == "One two"
    assert saved["meeting"]["review_segments"][0]["text"] == "Edited words"
    assert saved["meeting"]["speaker_names"]["SPEAKER_00"] == "Alice"
    assert operations == [False, True]
    assert len(stopped) == len(released) == 2
    manager.shutdown()


def test_meeting_start_finish_processes_to_reviewable_session(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)

    started = manager.start_realtime(_single_microphone(), language="it", num_speakers=1, pipeline="whisper")
    assert started["status"] == "recording"
    assert started["mode"] == "realtime"

    finishing = manager.finish()
    assert finishing["status"] == "finishing"
    runtime = manager._runtime
    assert runtime is not None
    _wait_until(lambda: manager.snapshot()["status"] == "completed")
    if runtime.processing_thread is not None:
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
    assert combined["meeting"]["speaker_diarization_segments"] == [
        {"start": 0.0, "end": 0.5, "speaker_id": "SPEAKER_00"}
    ]
    assert Path(combined["meeting"]["recording"]["path"]).is_file()


def test_rerun_diarization_reuses_raw_segments_without_starting_whisper(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)
    session_id = _completed_meeting(manager)
    raw_before = controller.history.get_session(session_id)
    assert raw_before is not None
    raw_segments = list(raw_before["segments"])
    raw_text = raw_before["text"]
    manager.set_speaker_name(session_id, "SPEAKER_00", "Marco")
    manager.edit_segment(session_id, 0, "Correzione manuale")
    starts_before = controller.backend_starts

    started = manager.rerun_diarization(session_id, num_speakers=4)
    assert started["operation"] == "rediarization"
    assert started["progress"] == 100
    _wait_until(lambda: manager.snapshot()["status"] == "completed")

    combined = manager.get(session_id)
    assert combined is not None
    assert controller.backend_starts == starts_before
    assert combined["text"] == raw_text
    assert combined["segments"] == raw_segments
    assert combined["meeting"]["num_speakers"] == 4
    assert combined["meeting"]["speaker_names"] == {"SPEAKER_00": "Marco"}
    assert combined["meeting"]["review_segments"][0]["text"] == "Correzione manuale"
    assert combined["meeting"]["review_segments"][0]["raw_text"] == "Ciao a tutti"
    assert manager.diarizer.calls[-1][1] == 4


def test_rerun_diarization_recovers_meeting_that_failed_after_whisper(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)
    session_id = _completed_meeting(manager)
    starts_before = controller.backend_starts
    manager.store.set_status(session_id, "error", terminal=True)

    manager.rerun_diarization(session_id, num_speakers=2)
    _wait_until(lambda: manager.snapshot()["status"] == "completed")

    combined = manager.get(session_id)
    assert combined is not None
    assert combined["status"] == "completed"
    assert combined["meeting"]["processing_status"] == "completed"
    assert combined["meeting"]["num_speakers"] == 2
    assert controller.backend_starts == starts_before


def test_rerun_diarization_requires_saved_audio(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    session_id = _completed_meeting(manager)
    assert manager.delete_audio(session_id) is True

    with pytest.raises(RuntimeError, match="Audio della riunione non disponibile"):
        manager.rerun_diarization(session_id, num_speakers=1)


def test_rerun_diarization_validates_speaker_count(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    session_id = _completed_meeting(manager)

    with pytest.raises(ValueError, match="tra 0 e 20"):
        manager.rerun_diarization(session_id, num_speakers=21)


def test_realtime_meeting_records_multiple_sources_as_tracks(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)

    started = manager.start_realtime(
        [
            {"source": "microphone", "selected_input": "Test Mic", "label": "Locale"},
            {"source": "system", "selected_input": "Test Monitor", "label": "Remoti"},
        ],
        language="it",
        num_speakers=0,
     pipeline="whisper")
    assert len(started["sources"]) == 2

    manager.finish()
    _wait_until(lambda: manager.snapshot()["status"] == "completed")
    combined = manager.get(started["id"])
    assert combined is not None
    acquisition = combined["meeting"]["acquisition"]
    assert acquisition["mode"] == "realtime"
    assert len(acquisition["sources"]) == 2
    assert {item["source"] for item in acquisition["sources"]} == {"microphone", "system"}
    assert all(Path(item["recording"]["path"]).is_file() for item in acquisition["sources"])
    assert Path(combined["meeting"]["recording"]["path"]).is_file()


def test_meeting_from_file_converges_on_same_analysis(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)
    source = tmp_path / "phone-recording.wav"
    sf.write(source, np.linspace(-0.1, 0.1, 8000, dtype=np.float32), 16000)

    started = manager.start_file(source, language="it", num_speakers=1, pipeline="whisper")
    assert started["mode"] == "file"
    assert started["status"] == "preparing_file"

    _wait_until(lambda: manager.snapshot()["status"] == "completed")
    combined = manager.get(started["id"])
    assert combined is not None
    assert combined["meeting"]["acquisition"]["mode"] == "file"
    assert combined["text"] == "Ciao a tutti"
    assert Path(combined["meeting"]["recording"]["path"]).is_file()
    assert controller.backend_starts == 1


def test_duplicate_realtime_source_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    try:
        manager.start_realtime(
            [
                {"source": "microphone", "selected_input": "Test Mic"},
                {"source": "microphone", "selected_input": "Test Mic"},
            ]
        , pipeline="whisper")
    except ValueError as exc:
        assert "due volte" in str(exc)
    else:
        raise AssertionError("Meeting must reject duplicate sources")


def test_finish_returns_while_capture_join_is_still_blocked(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path, capture_cls=_BlockingCapture)
    manager.start_realtime(_single_microphone(), pipeline="whisper")
    runtime = manager._runtime
    assert runtime is not None and runtime.capture is not None
    capture = runtime.capture.tracks[0].capture

    result = manager.finish()

    assert result["status"] == "finishing"
    assert capture.join_entered.wait(timeout=0.5)
    assert capture.is_alive()
    assert manager.snapshot()["status"] == "finishing"

    capture.release_join.set()
    _wait_until(lambda: manager.snapshot()["status"] == "completed")


def test_cancel_returns_while_capture_join_is_still_blocked(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path, capture_cls=_BlockingCapture)
    manager.start_realtime(_single_microphone(), pipeline="whisper")
    runtime = manager._runtime
    assert runtime is not None and runtime.capture is not None
    capture = runtime.capture.tracks[0].capture

    manager.cancel()

    assert capture.join_entered.wait(timeout=0.5)
    assert capture.is_alive()
    assert manager.snapshot()["status"] == "cancelling"

    capture.release_join.set()
    _wait_until(lambda: manager.snapshot()["status"] == "cancelled")


def test_meeting_is_exclusive_with_live_and_file(monkeypatch, tmp_path: Path) -> None:
    controller, manager = _manager(monkeypatch, tmp_path)
    controller.live_count = 1
    try:
        manager.start_realtime(_single_microphone(), pipeline="whisper")
    except RuntimeError as exc:
        assert "Live/File" in str(exc)
    else:
        raise AssertionError("Meeting must reject active Live")

    controller.live_count = 0
    controller.file_busy = True
    try:
        manager.start_realtime(_single_microphone(), pipeline="whisper")
    except RuntimeError as exc:
        assert "Live/File" in str(exc)
    else:
        raise AssertionError("Meeting must reject active File")


def test_shutdown_during_recording_preserves_audio_and_marks_interrupted(monkeypatch, tmp_path: Path) -> None:
    _, manager = _manager(monkeypatch, tmp_path)
    started = manager.start_realtime(_single_microphone(), pipeline="whisper")

    manager.shutdown()

    combined = manager.get(started["id"])
    assert combined is not None
    assert combined["status"] == "interrupted"
    recording = combined["meeting"]["recording"]
    assert recording["path"].endswith(".flac")
    assert Path(recording["path"]).is_file()
    assert len(combined["meeting"]["acquisition"]["sources"]) == 1


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

    resolver = AudioInputResolver(
        router=type("Router", (), {})(),
        sink_resolver=lambda selected, source: selected or f"{source}-auto",
    )
    manager = MeetingManager(controller, resolver)
    assert entered.wait(timeout=1.0)
    assert manager._recovery_thread.is_alive()

    release.set()
    manager._recovery_thread.join(timeout=1.0)
    assert not manager._recovery_thread.is_alive()
