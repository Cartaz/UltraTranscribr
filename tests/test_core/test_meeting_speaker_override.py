from __future__ import annotations

from pathlib import Path

import pytest

from core.meeting_store import MeetingStore
from core.transcript_history import TranscriptHistoryStore


def _store_with_review(tmp_path: Path) -> tuple[MeetingStore, str]:
    history = TranscriptHistoryStore(tmp_path / "history")
    store = MeetingStore(history, tmp_path / "meetings")
    session_id = store.create(
        model="large-v3",
        language="it",
        source="file",
        source_path="meeting.wav",
        num_speakers=2,
    )
    history.append_text(session_id, "Ciao")
    history.append_segments(
        session_id,
        [{"start": 0.0, "end": 1.0, "text": "Ciao"}],
    )
    store.set_diarization(
        session_id,
        diarization_segments=[
            {"start": 0.0, "end": 0.5, "speaker_id": "SPEAKER_00"},
            {"start": 0.5, "end": 1.0, "speaker_id": "SPEAKER_01"},
        ],
        speaker_diarization_segments=[
            {"start": 0.0, "end": 0.6, "speaker_id": "SPEAKER_00"},
            {"start": 0.4, "end": 1.0, "speaker_id": "SPEAKER_01"},
        ],
        review_segments=[
            {
                "start": 0.0,
                "end": 1.0,
                "raw_text": "Ciao",
                "text": "Ciao",
                "speaker_id": None,
                "uncertain": True,
                "speaker_candidates": ["SPEAKER_00", "SPEAKER_01"],
            }
        ],
        num_speakers=2,
    )
    return store, session_id


def test_manual_override_does_not_destroy_automatic_assignment(tmp_path: Path) -> None:
    store, session_id = _store_with_review(tmp_path)

    store.set_review_speaker_override(session_id, 0, "SPEAKER_01")

    meeting = store.get(session_id)
    assert meeting is not None
    segment = meeting["meeting"]["review_segments"][0]
    assert segment["speaker_id"] is None
    assert segment["speaker_override"] == "SPEAKER_01"
    assert store.rendered_text(session_id) == "Speaker 2: Ciao"


def test_manual_override_uses_custom_speaker_name_in_export(tmp_path: Path) -> None:
    store, session_id = _store_with_review(tmp_path)
    store.set_speaker_name(session_id, "SPEAKER_01", "Maria")
    store.set_review_speaker_override(session_id, 0, "SPEAKER_01")

    target = store.export(session_id, tmp_path / "review", "txt")

    assert target.read_text(encoding="utf-8") == "Maria: Ciao\n"


def test_clearing_override_returns_review_to_automatic_assignment(tmp_path: Path) -> None:
    store, session_id = _store_with_review(tmp_path)
    store.set_review_speaker_override(session_id, 0, "SPEAKER_01")

    store.set_review_speaker_override(session_id, 0, "")

    meeting = store.get(session_id)
    assert meeting is not None
    segment = meeting["meeting"]["review_segments"][0]
    assert "speaker_override" not in segment
    assert store.rendered_text(session_id) == "Speaker ?: Ciao"


def test_unknown_speaker_override_is_rejected(tmp_path: Path) -> None:
    store, session_id = _store_with_review(tmp_path)

    with pytest.raises(ValueError, match="non presente"):
        store.set_review_speaker_override(session_id, 0, "SPEAKER_99")


def test_old_meeting_sidecar_defaults_regular_diarization_to_empty(tmp_path: Path) -> None:
    store, session_id = _store_with_review(tmp_path)
    path = store.root / f"{session_id}.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("speaker_diarization_segments", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    meeting = store.get(session_id)

    assert meeting is not None
    assert meeting["meeting"]["speaker_diarization_segments"] == []
