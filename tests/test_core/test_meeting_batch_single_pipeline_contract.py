from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_batch_contains_no_duplicate_transcription_or_diarization_algorithm() -> None:
    source = (ROOT / "core" / "meeting_batch.py").read_text(encoding="utf-8")

    assert "normalize_media_to_flac" not in source
    assert "align_speakers" not in source
    assert "ensure_backend_started" not in source
    assert "start_file(" in source
