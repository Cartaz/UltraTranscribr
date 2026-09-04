from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_file_selection_reports_multiple_recordings_without_persisting_paths() -> None:
    web = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert "meetingFilePaths = [...new Set" in web
    assert "registrazioni selezionate" in web
    assert "meetingFilePaths = [];" in web
    assert "localStorage" not in web
