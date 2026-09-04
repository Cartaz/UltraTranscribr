from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_is_owned_below_webchannel_and_reuses_meeting_pipeline() -> None:
    coordinator = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    bridge = (ROOT / "ui" / "bridge.py").read_text(encoding="utf-8")

    assert "class MeetingBatchCoordinator" in coordinator
    assert "self._manager.start_file(" in coordinator
    assert "FileTranscriberThread" not in coordinator
    assert "SpeakerDiarizer" not in coordinator
    assert "EventBus" not in coordinator
    assert "self.meeting_batch = MeetingBatchCoordinator(" in application
    assert "def enqueue_meeting_files" in application
    assert "def list_meeting_queue" in application
    assert "def cancel_meeting_queue" in application
    assert "def clear_finished_meeting_queue" in application
    assert "def enqueueMeetingBatch" in bridge
    assert "self._application.enqueue_meeting_files(" in bridge
    assert '"meeting_queue_changed"' in bridge
    assert '"meeting_queue_job_updated"' in bridge


def test_meeting_recording_picker_and_queue_support_multiple_files() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "let meetingFilePaths = [];" in web
    assert 'call("chooseAudioFiles"' in web
    assert 'call("enqueueMeetingBatch"' in web
    assert 'id="meeting-batch-list"' in web
    assert 'id="meeting-batch-cancel"' in web
    assert 'id="meeting-batch-clear"' in web
    assert "meetingBatchIsBusy" in web
    assert "meetingRenderBatchQueue" in web
    assert "transcription_progress" in web
    assert "diarization_progress" in web
    assert "una alla volta" in web


def test_batch_completion_refreshes_archive_without_forcing_review_open() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    handler = web.split('if (name === "meeting_completed")', 1)[1].split(
        'if (name === "meeting_error")', 1
    )[0]
    assert "meetingBatchJobForSession" in handler
    assert "meetingRefreshList();" in handler
    assert "if (batchJob)" in handler
    assert "meetingLoad(String(value));" in handler
    assert handler.index("if (batchJob)") < handler.index("meetingLoad(String(value));")


def test_meeting_batch_locks_competing_workflows_and_backend_settings() -> None:
    application = (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "self.meeting.is_busy() or self.meeting_batch.is_busy()" in application
    assert "self.controller.dictation_busy()" in application
    assert '"meetingQueue": self.meeting_batch.list_jobs()' in application
    assert '"meetingBatchBusy": self.meeting_batch.is_busy()' in application
    assert "return meetingRuntimeIsBusy() || meetingBatchIsBusy();" in web
    assert '$("meeting-mode-realtime").disabled = active' in web
    assert '$("meeting-language").disabled = active' in web


def test_meeting_batch_ui_has_dedicated_neumorphic_queue_styles() -> None:
    css = (ROOT / "ui" / "web" / "meeting.css").read_text(encoding="utf-8")

    for token in (
        ".meeting-batch-card",
        ".meeting-batch-list",
        ".meeting-batch-item",
        ".meeting-batch-progress-stack",
        ".meeting-batch-progress",
    ):
        assert token in css
