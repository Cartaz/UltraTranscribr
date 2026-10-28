"""Frozen acoustic timing policy for the optional English meeting pipeline.

CTC timing is primary; the Qwen aligner supplies timing where CTC has no
alignment or probability below 0.2. Neither aligner may change the ASR text.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from core.word_timing import lexical_words

CTC_TIMING_THRESHOLD = 0.2


def combine_word_timings(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    duration_s: float,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return copied rows, changed-word count and monotone-start clamp count.

    This is the switch02 policy validated on the three public ICSI recordings.
    Invalid alignment data is rejected instead of silently changing the text.
    """
    if not math.isfinite(duration_s) or duration_s <= 0.001:
        raise ValueError("Invalid audio duration for acoustic alignment")
    if [row.get("text") for row in primary] != [row.get("text") for row in secondary]:
        raise ValueError("Acoustic alignments do not contain the same transcript")
    rows = copy.deepcopy(primary)
    changes = clamps = 0
    for index, (first, second) in enumerate(zip(primary, secondary)):
        for row in (first, second):
            for word in row.get("words", []):
                if not all(math.isfinite(float(word[key])) for key in ("start", "end")):
                    raise ValueError(
                        "Acoustic alignment contains non-finite timestamps"
                    )
        alternative, _ = lexical_words(second["text"], second.get("words", []))
        words = first.get("words") or []
        if not alternative or len(words) != len(alternative):
            raise ValueError("Acoustic alignments do not contain the same words")
        previous = -1.0
        for position, (word, other) in enumerate(zip(words, alternative)):
            if "".join(word["word"].split()) != "".join(other["word"].split()):
                raise ValueError("Acoustic alignment changed a recognized word")
            probability = word.get("alignment_probability")
            fallback = bool(word.get("alignment_fallback")) or probability is None
            if probability is not None:
                score = float(probability)
                fallback = (
                    fallback or not math.isfinite(score) or score < CTC_TIMING_THRESHOLD
                )
            weight = float(fallback)
            times = [
                float(item[key]) for item in (word, other) for key in ("start", "end")
            ]
            if not all(math.isfinite(value) for value in times):
                raise ValueError("Acoustic alignment contains non-finite timestamps")
            start = (1 - weight) * word["start"] + weight * other["start"]
            end = (1 - weight) * word["end"] + weight * other["end"]
            if start < previous:
                clamps += 1
                start = previous
            start = max(0.0, min(start, duration_s - 0.001))
            end = min(duration_s, max(end, start + 0.001))
            changes += (
                abs(start - word["start"]) > 1e-9 or abs(end - word["end"]) > 1e-9
            )
            rows[index]["words"][position].update(
                start=start, end=end, secondary_timing_weight=weight
            )
            previous = start
        if "".join(word["word"] for word in rows[index]["words"]) != first["text"]:
            raise ValueError("Acoustic alignment did not preserve the transcript")
        rows[index]["start"] = min(
            first["start"], min(word["start"] for word in rows[index]["words"])
        )
        rows[index]["end"] = max(
            first["end"], max(word["end"] for word in rows[index]["words"])
        )
    return rows, changes, clamps
