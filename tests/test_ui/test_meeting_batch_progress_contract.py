from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_shows_transcription_and_diarization_progress_separately() -> None:
    source = (ROOT / "ui" / "web" / "meeting.js").read_text(encoding="utf-8")

    assert '[["Whisper", job.transcription_progress], ["Speaker", job.diarization_progress]]' in source
    assert 'role", "progressbar"' in source
