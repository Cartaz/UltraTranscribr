from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_queue_state_is_python_owned_and_not_persisted_in_js() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "self._jobs: list[MeetingBatchJob]" in source
    assert '"meetingQueue": self.meeting_batch.list_jobs()' in (ROOT / "core" / "application_service.py").read_text(encoding="utf-8")
    assert "localStorage" not in web
