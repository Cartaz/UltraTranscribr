from __future__ import annotations

from core.file_transcriber import FileTranscriberThread
from core.transcript_export import normalize_segments
from core.transcript_history import TranscriptHistoryStore


def test_chunk_normalization_globalizes_word_timestamps_and_drops_overlap_prefix() -> None:
    raw = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "vecchio nuovo testo",
            "words": [
                {"word": " vecchio", "start": 0.0, "end": 0.4, "probability": 0.8},
                {"word": " nuovo", "start": 0.7, "end": 1.1, "probability": 0.9},
                {"word": " testo", "start": 1.1, "end": 1.7, "probability": 0.95},
            ],
        }
    ]

    segments = FileTranscriberThread._normalize_chunk_segments(
        raw,
        chunk_offset_s=10.0,
        committed_before_s=10.5,
    )

    assert len(segments) == 1
    assert segments[0]["start"] == 10.5
    assert segments[0]["end"] == 12.0
    assert [word["word"] for word in segments[0]["words"]] == [" nuovo", " testo"]
    assert segments[0]["words"][0]["start"] == 10.7
    assert segments[0]["words"][1]["end"] == 11.7
    assert segments[0]["words"][1]["probability"] == 0.95


def test_normalize_segments_preserves_words_without_affecting_segment_shape() -> None:
    normalized = normalize_segments(
        [
            {
                "start": 1.0,
                "end": 2.0,
                "text": "Ciao mondo",
                "words": [
                    {"word": " Ciao", "start": 1.0, "end": 1.3, "probability": 0.99},
                    {"word": " mondo", "start": 1.3, "end": 1.9, "probability": 0.98},
                ],
            }
        ]
    )

    assert normalized[0]["text"] == "Ciao mondo"
    assert normalized[0]["words"][0] == {
        "word": " Ciao",
        "start": 1.0,
        "end": 1.3,
        "probability": 0.99,
    }


def test_transcript_history_persists_optional_word_timing(tmp_path) -> None:
    history = TranscriptHistoryStore(tmp_path / "history")
    session_id = history.create_session(
        kind="meeting",
        model="large-v3",
        language="it",
        source="file",
        source_path="meeting.wav",
    )
    history.append_segments(
        session_id,
        [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Una frase",
                "words": [
                    {"word": " Una", "start": 0.1, "end": 0.35},
                    {"word": " frase", "start": 0.35, "end": 0.8},
                ],
            }
        ],
    )

    session = history.get_session(session_id)

    assert session is not None
    assert [word["word"] for word in session["segments"][0]["words"]] == [
        " Una",
        " frase",
    ]
