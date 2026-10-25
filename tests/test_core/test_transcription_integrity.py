"""Regressions from long Italian meeting exports, with anonymized examples."""

from core.meeting_alignment import align_speakers, preserve_review_edits
from core.transcript_export import normalize_segments, render_srt


def test_equal_timestamps_preserve_lexical_order_and_repeated_zero_duration_words():
    text = [
        "osservazione",
        "sui bambini che sia",
        "la primavera che sia",
        "l'infanzia",
        "sì",
        "sì",
    ]
    rows = [{"start": 786.0, "end": 786.0, "text": word} for word in text]
    assert [r["text"] for r in normalize_segments(rows)] == text
    rendered = render_srt(rows)
    assert rendered.index("osservazione") < rendered.index("l'infanzia")
    assert rendered.count("\nsì\n") == 2


def test_subword_tokens_never_create_a_change_of_voice_inside_one_word():
    transcript = [
        {
            "start": 0,
            "end": 1,
            "text": "insomma",
            "words": [
                {"word": " ins", "start": 0, "end": 0.4},
                {"word": "omma", "start": 0.4, "end": 1},
            ],
        }
    ]
    turns = [
        {"start": 0, "end": 0.4, "speaker_id": "SPEAKER_00"},
        {"start": 0.4, "end": 1, "speaker_id": "SPEAKER_01"},
    ]
    result = align_speakers(transcript, turns)
    assert len(result) == 1 and result[0]["text"] == "insomma"
    assert result[0]["source_word_start"] == 0 and result[0]["source_word_end"] == 2


def test_incomplete_tokens_cannot_delete_recognized_segment_text():
    transcript = [
        {
            "start": 0,
            "end": 2,
            "text": "non scegliere il rispetto",
            "words": [
                {"word": "ere", "start": 0, "end": 0.4},
                {"word": " il", "start": 0.4, "end": 0.6},
                {"word": " rispetto", "start": 0.6, "end": 2},
            ],
        }
    ]
    result = align_speakers(
        transcript, [{"start": 0, "end": 2, "speaker_id": "SPEAKER_00"}]
    )
    assert result[0]["text"] == "non scegliere il rispetto"
    assert result[0]["alignment"] == "segment"
    assert "word_text_mismatch" in result[0]["alignment_warnings"]


def test_degenerate_word_times_use_whole_segment_and_keep_the_warning():
    transcript = [
        {
            "start": 0,
            "end": 2,
            "text": "una frase",
            "words": [
                {"word": " una", "start": 0, "end": 0},
                {"word": " frase", "start": 0, "end": 0},
            ],
        }
    ]
    result = align_speakers(
        transcript, [{"start": 0, "end": 2, "speaker_id": "SPEAKER_00"}]
    )
    assert result[0]["end"] == 2 and result[0]["text"] == "una frase"
    assert result[0]["alignment_warnings"] == ["degenerate_word_timing"]


def test_ordinary_word_api_without_leading_spaces_preserves_spaces():
    transcript = [
        {
            "start": 0,
            "end": 2,
            "text": "una frase",
            "words": [
                {"word": "una", "start": 0, "end": 1},
                {"word": "frase", "start": 1, "end": 2},
            ],
        }
    ]
    assert align_speakers(transcript, [])[0]["text"] == "una frase"


def gap_transcript():
    return [
        {
            "start": 0,
            "end": 2,
            "text": "una sola frase",
            "words": [
                {"word": " una", "start": 0, "end": 0.8},
                {"word": " sola", "start": 0.8, "end": 1.1},
                {"word": " frase", "start": 1.1, "end": 2},
            ],
        }
    ]


def test_short_uncovered_word_can_use_acoustic_continuity_with_annotation():
    turns = [
        {"start": 0, "end": 0.8, "speaker_id": "SPEAKER_00"},
        {"start": 1.1, "end": 2, "speaker_id": "SPEAKER_00"},
    ]
    result = align_speakers(gap_transcript(), turns)
    assert len(result) == 1 and result[0]["speaker_id"] == "SPEAKER_00"
    assert result[0]["alignment_warnings"] == ["diarization_gap_bridged"]


def test_short_real_interjection_is_not_absorbed_by_neighboring_voice():
    turns = [
        {"start": 0, "end": 0.8, "speaker_id": "SPEAKER_00"},
        {"start": 0.8, "end": 1.1, "speaker_id": "SPEAKER_01"},
        {"start": 1.1, "end": 2, "speaker_id": "SPEAKER_00"},
    ]
    result = align_speakers(gap_transcript(), turns, turns)
    assert [row["speaker_id"] for row in result] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_00",
    ]


def test_competing_regular_voice_prevents_bridging_exclusive_gap():
    exclusive = [
        {"start": 0, "end": 0.8, "speaker_id": "SPEAKER_00"},
        {"start": 1.1, "end": 2, "speaker_id": "SPEAKER_00"},
    ]
    regular = [*exclusive, {"start": 0.85, "end": 1.05, "speaker_id": "SPEAKER_01"}]
    result = align_speakers(gap_transcript(), exclusive, regular)
    assert result[1]["speaker_id"] is None and result[1]["uncertain"]


def test_resume_with_a_different_acoustic_voice_does_not_inherit_previous_speaker():
    turns = [
        {"start": 0, "end": 0.8, "speaker_id": "SPEAKER_00"},
        {"start": 1.1, "end": 2, "speaker_id": "SPEAKER_01"},
    ]
    result = align_speakers(gap_transcript(), turns)
    assert result[1]["speaker_id"] is None
    assert result[-1]["speaker_id"] == "SPEAKER_01"


def test_manual_sentence_and_override_survive_changed_word_group_boundaries():
    old = [
        {
            "start": 0,
            "end": 2,
            "raw_text": "una frase",
            "text": "Una frase corretta.",
            "alignment": "word",
            "source_segment_index": 0,
            "source_word_start": 0,
            "source_word_end": 2,
            "speaker_id": "SPEAKER_00",
            "speaker_override": "SPEAKER_00",
        }
    ]
    new = [
        {
            "start": i,
            "end": i + 1,
            "raw_text": word,
            "text": word,
            "alignment": "word",
            "source_segment_index": 0,
            "source_word_start": i,
            "source_word_end": i + 1,
            "speaker_id": f"SPEAKER_0{i}",
            "uncertain": False,
        }
        for i, word in enumerate(["una", "frase"])
    ]
    result = preserve_review_edits(old, new)
    assert len(result) == 1 and result[0]["text"] == "Una frase corretta."
    assert result[0]["speaker_override"] == "SPEAKER_00"
    assert result[0]["speaker_id"] is None and result[0]["uncertain"]
    assert result[0]["alignment_recovery_text"] == "una frase"
