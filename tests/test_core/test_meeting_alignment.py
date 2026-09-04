from __future__ import annotations

from core.meeting_alignment import (
    align_speakers,
    effective_speaker_id,
    preserve_review_edits,
)


def test_word_timestamps_split_one_whisper_segment_at_speaker_handoff() -> None:
    transcript = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Come reagisce? No, è tranquilla.",
            "words": [
                {"word": " Come", "start": 0.05, "end": 0.35},
                {"word": " reagisce?", "start": 0.35, "end": 0.85},
                {"word": " No,", "start": 1.05, "end": 1.25},
                {"word": " è", "start": 1.25, "end": 1.38},
                {"word": " tranquilla.", "start": 1.38, "end": 1.9},
            ],
        }
    ]
    exclusive = [
        {"start": 0.0, "end": 0.95, "speaker_id": "SPEAKER_00"},
        {"start": 0.95, "end": 2.0, "speaker_id": "SPEAKER_01"},
    ]

    review = align_speakers(transcript, exclusive)

    assert len(review) == 2
    assert review[0]["speaker_id"] == "SPEAKER_00"
    assert review[0]["raw_text"] == "Come reagisce?"
    assert review[0]["source_word_start"] == 0
    assert review[0]["source_word_end"] == 2
    assert review[1]["speaker_id"] == "SPEAKER_01"
    assert review[1]["raw_text"] == "No, è tranquilla."
    assert review[1]["source_word_start"] == 2
    assert review[1]["source_word_end"] == 5
    assert all(item["alignment"] == "word" for item in review)


def test_old_transcript_without_words_keeps_segment_level_fallback() -> None:
    transcript = [{"start": 0.0, "end": 2.0, "text": "Vecchia riunione"}]
    exclusive = [
        {"start": 0.0, "end": 1.8, "speaker_id": "SPEAKER_00"},
        {"start": 1.8, "end": 2.0, "speaker_id": "SPEAKER_01"},
    ]

    review = align_speakers(transcript, exclusive)

    assert len(review) == 1
    assert review[0]["alignment"] == "segment"
    assert review[0]["speaker_id"] == "SPEAKER_00"
    assert review[0]["raw_text"] == "Vecchia riunione"


def test_regular_diarization_marks_only_true_simultaneous_overlap() -> None:
    transcript = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Frase",
            "words": [{"word": " Frase", "start": 0.2, "end": 1.8}],
        }
    ]
    exclusive = [{"start": 0.0, "end": 2.0, "speaker_id": "SPEAKER_00"}]
    overlapping = [
        {"start": 0.0, "end": 1.2, "speaker_id": "SPEAKER_00"},
        {"start": 0.8, "end": 2.0, "speaker_id": "SPEAKER_01"},
    ]
    sequential = [
        {"start": 0.0, "end": 1.0, "speaker_id": "SPEAKER_00"},
        {"start": 1.0, "end": 2.0, "speaker_id": "SPEAKER_01"},
    ]

    overlap_review = align_speakers(transcript, exclusive, overlapping)
    sequential_review = align_speakers(transcript, exclusive, sequential)

    assert overlap_review[0]["overlap_speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert "overlap_speakers" not in sequential_review[0]


def test_uncertain_word_assignment_can_remain_explicit_for_manual_review() -> None:
    transcript = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Sì",
            "words": [{"word": " Sì", "start": 0.45, "end": 0.55}],
        }
    ]
    exclusive = [
        {"start": 0.0, "end": 0.5, "speaker_id": "SPEAKER_00"},
        {"start": 0.5, "end": 1.0, "speaker_id": "SPEAKER_01"},
    ]

    review = align_speakers(transcript, exclusive)

    assert review[0]["speaker_id"] is None
    assert review[0]["uncertain"] is True
    assert review[0]["speaker_candidates"] == ["SPEAKER_00", "SPEAKER_01"]


def test_manual_text_and_speaker_override_survive_same_word_group_rerun() -> None:
    previous = [
        {
            "start": 0.0,
            "end": 0.9,
            "raw_text": "Come reagisce?",
            "text": "Come reagisce lei?",
            "speaker_id": None,
            "speaker_override": "SPEAKER_00",
            "alignment": "word",
            "source_segment_index": 3,
            "source_word_start": 0,
            "source_word_end": 2,
        }
    ]
    rerun = [
        {
            "start": 0.01,
            "end": 0.91,
            "raw_text": "Come reagisce?",
            "text": "Come reagisce?",
            "speaker_id": "SPEAKER_01",
            "alignment": "word",
            "source_segment_index": 3,
            "source_word_start": 0,
            "source_word_end": 2,
        }
    ]

    preserved = preserve_review_edits(previous, rerun)

    assert preserved[0]["text"] == "Come reagisce lei?"
    assert preserved[0]["speaker_id"] == "SPEAKER_01"
    assert preserved[0]["speaker_override"] == "SPEAKER_00"
    assert effective_speaker_id(preserved[0]) == "SPEAKER_00"


def test_effective_speaker_falls_back_to_automatic_when_override_cleared() -> None:
    assert effective_speaker_id(
        {"speaker_id": "SPEAKER_02", "speaker_override": ""}
    ) == "SPEAKER_02"
    assert effective_speaker_id({"speaker_id": None}) is None
