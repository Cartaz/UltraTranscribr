"""Lifecycle coverage for controller-managed transcript autosave."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from config.settings import Settings
from core.app_controller import AppController
from core.event_bus import EventBus
from core.transcript_history import TranscriptHistoryStore


@pytest.fixture
def controller(tmp_path: Path) -> AppController:
    with patch("core.app_controller.detect_gpu_backend", return_value="sycl"), \
         patch("core.app_controller.WhisperModelManager"), \
         patch("core.app_controller.WhisperBackend"):
        instance = AppController(settings=Settings(history_retention_days=0))
    instance._history = TranscriptHistoryStore(tmp_path / "history")
    return instance


def test_live_autosave_lifecycle(controller: AppController) -> None:
    with patch.object(controller, "_run_async") as run_async:
        controller.start_transcription(
            sink_name="speaker.monitor",
            audio_source="firefox",
            language="it",
        )
    run_async.assert_called_once()

    records = controller.list_history(10)
    assert len(records) == 1
    session_id = records[0]["id"]
    assert records[0]["status"] == "starting"

    bus = EventBus()
    bus.emit("process_started", {"sink": "speaker.monitor", "source": "firefox"})
    bus.emit("transcriber_new_text", "prima parte")
    bus.emit("transcriber_new_text", "seconda parte")
    bus.emit("transcriber_drained", None)

    session = controller.get_history_session(session_id)
    assert session is not None
    assert session["status"] == "completed"
    assert session["ended_at"] is not None
    assert session["text"] == "prima parte seconda parte"
    assert session["source"] == "firefox"
    assert session["source_path"] == "speaker.monitor"


def test_file_autosave_lifecycle(controller: AppController) -> None:
    with patch.object(controller, "_run_async") as run_async:
        controller.start_file_transcription(
            "/tmp/example.wav",
            language="en",
            model_size="medium",
        )
    run_async.assert_called_once()

    records = controller.list_history(10)
    assert len(records) == 1
    session_id = records[0]["id"]

    bus = EventBus()
    bus.emit("file_transcriber_status_changed", "running")
    bus.emit("file_transcriber_new_text", "hello")
    bus.emit("file_transcriber_new_text", "world")
    bus.emit("file_transcriber_completed", None)

    session = controller.get_history_session(session_id)
    assert session is not None
    assert session["status"] == "completed"
    assert session["text"] == "hello world"
    assert session["model"] == "medium"
    assert session["language"] == "en"
    assert session["source_path"] == "/tmp/example.wav"


def test_active_history_record_cannot_be_deleted(controller: AppController) -> None:
    with patch.object(controller, "_run_async"):
        controller.start_transcription(
            sink_name="speaker.monitor",
            audio_source="firefox",
            language="it",
        )
    session_id = controller.list_history(10)[0]["id"]

    with pytest.raises(RuntimeError):
        controller.delete_history_session(session_id)


def test_recovery_uses_file_pipeline_with_recovery_metadata(
    controller: AppController, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    recovery = cache / "recovery-live-123.wav"
    recovery.write_bytes(b"RIFF" + b"x" * 64)

    with patch("core.transcript_history.AppMeta.CACHE_DIR", cache), \
         patch.object(controller, "start_file_transcription") as start_file:
        controller.start_recovery_transcription(str(recovery))

    start_file.assert_called_once_with(
        str(recovery.resolve()),
        language=controller.settings.language,
        model_size=controller.settings.model_size,
        song_mode=False,
        isolate_vocals_flag=False,
        history_source="recovery",
    )
