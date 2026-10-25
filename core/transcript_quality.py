"""Bounded, non-destructive checks for decoder loops and uncovered audio.

Energy is not proof of speech: uncovered energetic audio is a review warning,
never a licence to invent words. Short authentic repetitions remain intact.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from core.word_timing import segment_interval


def quality_issues(
    text: str, segments: list[dict[str, Any]], pcm16: bytes = b""
) -> list[dict[str, Any]]:
    segments = [segment for segment in segments if isinstance(segment, dict)]
    words = re.findall(r"\w+(?:['’]\w+)*", text.lower())
    if not words:
        words = re.findall(
            r"\w+", " ".join(str(s.get("text") or "") for s in segments).lower()
        )
    issues = []
    intervals = [
        interval
        for segment in segments
        if (interval := segment_interval(segment)) is not None
    ]
    if segments and "".join(text.split()) != "".join(
        "".join(str(s.get("text") or "").split()) for s in segments
    ):
        issues.append({"reason": "segment_text_mismatch"})
    for size in range(1, min(8, len(words) // 3) + 1):
        for start in range(len(words) - size * 3 + 1):
            phrase = words[start : start + size]
            end = start + size
            while words[end : end + size] == phrase:
                end += size
            repeats = (end - start) // size
            if (size == 1 and repeats >= 8) or (
                size > 1 and repeats >= 3 and end - start >= 12
            ):
                issues.append(
                    {
                        "reason": "repetition_loop",
                        "word_start": start,
                        "word_end": end,
                        "repeats": repeats,
                    }
                )
                break
        if any(issue["reason"] == "repetition_loop" for issue in issues):
            break
    for segment in segments:
        pieces = segment.get("words")
        # Ordinary-word APIs omit leading spaces. Compare the actual letters,
        # not the spacing convention of a particular backend.
        if (
            isinstance(pieces, list)
            and pieces
            and "".join(
                "".join(str(w.get("word") or "").split())
                for w in pieces
                if isinstance(w, dict)
            )
            != "".join(str(segment.get("text") or "").split())
        ):
            issues.append(
                {
                    "reason": "word_text_mismatch",
                    "start": (segment_interval(segment) or (0, 0))[0],
                    "end": (segment_interval(segment) or (0, 0))[1],
                }
            )
            break
    if pcm16:
        frames = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768
        frame_size = 8000  # 0.5 s at the canonical 16 kHz rate.
        active_run = None
        for index in range(0, len(frames), frame_size):
            sample = frames[index : index + frame_size]
            start, end = index / 16000, (index + len(sample)) / 16000
            active = (
                bool(len(sample)) and float(np.sqrt(np.mean(sample * sample))) > 0.005
            )
            covered = any(lo <= (start + end) / 2 < hi for lo, hi in intervals)
            # A text-only API does not provide coverage evidence either way.
            uncovered = active and not covered and (bool(segments) or not text.strip())
            if uncovered and active_run is None:
                active_run = start
            if active_run is not None and (not uncovered or end == len(frames) / 16000):
                until = start if not uncovered else end
                if until - active_run >= 2:
                    issues.append(
                        {"reason": "uncovered_audio", "start": active_run, "end": until}
                    )
                active_run = None
    return issues
