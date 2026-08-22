from core.speaker_diarization import align_speakers, speaker_label


def test_align_speakers_assigns_dominant_temporal_overlap() -> None:
    transcript = [
        {"start": 0.0, "end": 4.0, "text": "Primo intervento"},
        {"start": 4.0, "end": 7.0, "text": "Secondo intervento"},
    ]
    diarization = [
        {"start": 0.0, "end": 3.6, "speaker_id": "SPEAKER_00"},
        {"start": 3.6, "end": 4.0, "speaker_id": "SPEAKER_01"},
        {"start": 4.0, "end": 7.0, "speaker_id": "SPEAKER_01"},
    ]

    review = align_speakers(transcript, diarization)

    assert review[0]["speaker_id"] == "SPEAKER_00"
    assert review[0]["uncertain"] is False
    assert review[0]["raw_text"] == review[0]["text"] == "Primo intervento"
    assert review[1]["speaker_id"] == "SPEAKER_01"


def test_align_speakers_marks_near_equal_overlap_uncertain() -> None:
    review = align_speakers(
        [{"start": 0.0, "end": 2.0, "text": "Voce sovrapposta"}],
        [
            {"start": 0.0, "end": 1.1, "speaker_id": "SPEAKER_00"},
            {"start": 0.9, "end": 2.0, "speaker_id": "SPEAKER_01"},
        ],
    )

    assert review[0]["speaker_id"] is None
    assert review[0]["uncertain"] is True
    assert review[0]["speaker_candidates"] == ["SPEAKER_00", "SPEAKER_01"]


def test_manual_speaker_names_only_change_display_label() -> None:
    names = {"SPEAKER_00": "Marco"}
    assert speaker_label("SPEAKER_00", names) == "Marco"
    assert speaker_label("SPEAKER_01", names) == "Speaker 2"
    assert speaker_label(None, names) == "Speaker ?"
