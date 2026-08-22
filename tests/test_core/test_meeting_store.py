import os
from pathlib import Path

from config.constants import AppMeta
from core.meeting_store import MeetingStore
from core.transcript_history import TranscriptHistoryStore


def _meeting(tmp_path: Path) -> tuple[TranscriptHistoryStore, MeetingStore, str]:
    history = TranscriptHistoryStore(tmp_path / "transcripts")
    store = MeetingStore(history, tmp_path / "meetings")
    session_id = store.create(
        model="medium",
        language="it",
        microphone="Test Mic",
        num_speakers=2,
    )
    history.append_text(session_id, "Testo raw originale")
    history.append_segments(
        session_id,
        [
            {"start": 0.0, "end": 1.0, "text": "Testo raw"},
            {"start": 1.0, "end": 2.0, "text": "originale"},
        ],
    )
    store.set_diarization(
        session_id,
        diarization_segments=[
            {"start": 0.0, "end": 1.0, "speaker_id": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "speaker_id": "SPEAKER_01"},
        ],
        review_segments=[
            {"start": 0.0, "end": 1.0, "raw_text": "Testo raw", "text": "Testo raw", "speaker_id": "SPEAKER_00", "uncertain": False, "speaker_candidates": ["SPEAKER_00"]},
            {"start": 1.0, "end": 2.0, "raw_text": "originale", "text": "originale", "speaker_id": "SPEAKER_01", "uncertain": False, "speaker_candidates": ["SPEAKER_01"]},
        ],
    )
    return history, store, session_id


def test_meeting_history_kind_and_sidecar_are_combined(tmp_path: Path) -> None:
    history, store, session_id = _meeting(tmp_path)

    combined = store.get(session_id)

    assert combined is not None
    assert combined["kind"] == "meeting"
    assert history.get_session(session_id)["kind"] == "meeting"
    assert combined["text"] == "Testo raw originale"
    assert combined["meeting"]["num_speakers"] == 2
    assert len(combined["meeting"]["review_segments"]) == 2
    assert history.get_session(session_id)["segments"][0]["text"] == "Testo raw"


def test_manual_review_edit_and_speaker_name_never_overwrite_raw(tmp_path: Path) -> None:
    history, store, session_id = _meeting(tmp_path)

    store.set_speaker_name(session_id, "SPEAKER_00", "Marco")
    store.edit_review_segment(session_id, 0, "Testo corretto manualmente")

    combined = store.get(session_id)
    assert combined is not None
    assert combined["meeting"]["speaker_names"]["SPEAKER_00"] == "Marco"
    assert combined["meeting"]["review_segments"][0]["text"] == "Testo corretto manualmente"
    assert combined["meeting"]["review_segments"][0]["raw_text"] == "Testo raw"
    assert history.get_session(session_id)["text"] == "Testo raw originale"
    assert history.get_session(session_id)["segments"][0]["text"] == "Testo raw"


def test_meeting_exports_use_manual_names_and_reviewed_text(tmp_path: Path) -> None:
    _, store, session_id = _meeting(tmp_path)
    store.set_speaker_name(session_id, "SPEAKER_00", "Marco")
    store.edit_review_segment(session_id, 0, "Correzione")

    txt = store.export(session_id, tmp_path / "meeting", "txt")
    srt = store.export(session_id, tmp_path / "meeting-subtitles", "srt")
    vtt = store.export(session_id, tmp_path / "meeting-captions", "vtt")

    assert "Marco: Correzione" in txt.read_text(encoding="utf-8")
    assert "Speaker 2: originale" in txt.read_text(encoding="utf-8")
    assert "Marco: Correzione" in srt.read_text(encoding="utf-8")
    assert vtt.read_text(encoding="utf-8").startswith("WEBVTT")


def test_meeting_audio_can_be_deleted_without_history(tmp_path: Path, monkeypatch) -> None:
    history, store, session_id = _meeting(tmp_path)
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    audio = recordings / f"{session_id}.flac"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)
    store.set_recording(session_id, {"path": str(audio), "duration_s": 1.0, "size_bytes": 4})

    assert store.delete_audio(session_id) is True
    assert not audio.exists()
    assert history.get_session(session_id)["text"] == "Testo raw originale"
    assert store.get(session_id)["meeting"]["recording"] == {}


def test_audio_retention_never_deletes_path_outside_recordings(tmp_path: Path, monkeypatch) -> None:
    _, store, session_id = _meeting(tmp_path)
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    monkeypatch.setattr(AppMeta, "RECORDINGS_DIR", recordings)

    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"must survive")
    os.utime(outside, (1, 1))
    store.set_recording(
        session_id,
        {"path": str(outside), "duration_s": 1.0, "size_bytes": outside.stat().st_size},
    )

    assert store.prune_audio(1) == 0
    assert outside.read_bytes() == b"must survive"
