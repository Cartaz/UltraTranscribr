from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_renders_filename_without_exposing_full_path_as_primary_text() -> None:
    source = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "function meetingFileName(path)" in source
    assert "title.textContent = meetingFileName(job.path)" in source
    assert 'title.title = job.path || ""' in source
