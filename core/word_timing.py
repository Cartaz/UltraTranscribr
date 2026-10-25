"""Reconcile backend token timing with the authoritative segment text.

whisper.cpp can expose subword tokens under ``words``. A token is not a
linguistic word and must never independently create a speaker hand-off. The
segment text also survives overlap trimming better than partial token lists:
when their content disagrees, callers retain the complete segment instead of
silently reconstructing a shorter sentence from those tokens.
"""

from __future__ import annotations

import math
import re
from itertools import pairwise
from typing import Any


def segment_interval(raw: dict[str, Any]) -> tuple[float, float] | None:
    """Decode the timing formats supported by whisper.cpp/server adapters."""
    try:
        if "start" in raw or "end" in raw:
            start = float(raw.get("start", 0))
            end = float(raw.get("end", start))
        elif "t0" in raw or "t1" in raw:
            start = float(raw.get("t0", 0)) * 0.01
            end = float(raw.get("t1", raw.get("t0", 0))) * 0.01
        elif isinstance(raw.get("offsets"), dict):
            offsets = raw["offsets"]
            start = float(offsets.get("from", 0)) / 1000
            end = float(offsets.get("to", offsets.get("from", 0))) / 1000
        else:
            return None
        if not math.isfinite(start) or not math.isfinite(end):
            return None
        return max(0.0, start), max(0.0, start, end)
    except (TypeError, ValueError):
        return None


def lexical_words(
    text: str,
    pieces: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return whole words with original token spans, or an explicit fallback.

    Whitespace comes from the segment text, so both leading-space BPE tokens
    and APIs returning ordinary words without leading spaces are supported.
    No missing letters, words, or synthetic word timestamps are invented.
    """
    spans: list[dict[str, Any]] = []
    compact = ""
    for index, piece in enumerate(pieces):
        value = str(piece.get("word") or "")
        chars = "".join(value.split())
        if not chars:
            continue
        try:
            start = float(piece["start"])
            end = float(piece["end"])
        except (KeyError, TypeError, ValueError):
            return [], ["invalid_word_timing"]
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            return [], ["invalid_word_timing"]
        spans.append(
            {
                "lo": len(compact),
                "hi": len(compact) + len(chars),
                "start": start,
                "end": end,
                "index": index,
                "probability": piece.get("probability"),
            }
        )
        compact += chars
    if compact != "".join(text.split()):
        return [], ["word_text_mismatch"]
    if not spans:
        return [], ["missing_word_timing"]

    output = []
    cursor = 0
    previous_end = 0
    for match in re.finditer(r"\S+", text):
        length = len(match.group())
        parts = [p for p in spans if p["lo"] < cursor + length and p["hi"] > cursor]
        # A single timing record spanning several lexical words has no finer
        # timing information. Preserve the segment rather than splitting it.
        if not parts or parts[0]["lo"] < cursor or parts[-1]["hi"] > cursor + length:
            return [], ["coarse_word_timing"]
        start = min(p["start"] for p in parts)
        end = max(p["end"] for p in parts)
        probabilities = []
        for part in parts:
            try:
                probability = float(part["probability"])
            except (TypeError, ValueError):
                continue
            if math.isfinite(probability):
                probabilities.append(probability)
        row = {
            "word": text[previous_end : match.end()],
            "start": start,
            "end": end,
            "source_word_start": parts[0]["index"],
            "source_word_end": parts[-1]["index"] + 1,
        }
        if probabilities:
            row["probability"] = min(probabilities)
        output.append(row)
        previous_end = match.end()
        cursor += length
    if any(word["end"] <= word["start"] for word in output):
        return [], ["degenerate_word_timing"]
    if any(b["start"] < a["start"] for a, b in pairwise(output)):
        return [], ["nonmonotonic_word_timing"]
    return output, []
