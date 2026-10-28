import copy

import pytest

from core.english_timing import combine_word_timings


def row(first=0.1, second=0.9):
    return {
        "text": "One two",
        "start": 0.0,
        "end": 3.0,
        "words": [
            {"word": "One", "start": 0.2, "end": 0.8, "alignment_probability": first},
            {"word": " two", "start": 1.0, "end": 1.5, "alignment_probability": second},
        ],
    }


def test_optional_alignment_preserves_text_and_inputs():
    primary = [row()]
    secondary = [row()]
    secondary[0]["words"][0].update(start=0.4, end=1.2)
    secondary[0]["words"][1].update(start=2.0, end=2.5)
    original = copy.deepcopy((primary, secondary))
    result, changes, clamps = combine_word_timings(primary, secondary, 3.0)
    assert (primary, secondary) == original
    assert "".join(word["word"] for word in result[0]["words"]) == "One two"
    assert result[0]["words"][0]["start"] == 0.4
    assert result[0]["words"][1]["start"] == 1.0
    assert changes == 1 and clamps == 0


def test_alignment_rejects_changed_text_and_nonfinite_times():
    first, second = [row()], [row()]
    second[0]["text"] = "One three"
    with pytest.raises(ValueError, match="same transcript"):
        combine_word_timings(first, second, 3.0)
    second = [row()]
    second[0]["words"][0]["start"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        combine_word_timings(first, second, 3.0)


def test_low_confidence_timing_cannot_reorder_or_escape_audio():
    first = [row(first=0.9, second=float("nan"))]
    second = [row()]
    first[0]["words"][0].update(start=2.8, end=4.0)
    result, _, clamps = combine_word_timings(first, second, 3.0)
    assert clamps == 1
    assert all(0 <= word["start"] < word["end"] <= 3 for word in result[0]["words"])
    assert result[0]["words"][0]["start"] <= result[0]["words"][1]["start"]
