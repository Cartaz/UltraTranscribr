"""Timestamp-preserving transcript export helpers."""

from __future__ import annotations

import math
from typing import Any, Iterable


def _timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _normalize_words(
    words: Any,
    *,
    segment_start: float,
    segment_end: float,
) -> list[dict[str, Any]]:
    """Validate optional Whisper word timing without changing its display text."""
    if not isinstance(words, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in words:
        if not isinstance(raw, dict):
            continue
        word = str(raw.get("word") or "")
        if not word.strip():
            continue
        try:
            start = max(segment_start, float(raw.get("start", segment_start)))
            end = min(segment_end, max(start, float(raw.get("end", start))))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        if start > segment_end or end < segment_start:
            continue
        item: dict[str, Any] = {
            "word": word,
            "start": start,
            "end": max(start, end),
        }
        try:
            probability = float(raw.get("probability"))
        except (TypeError, ValueError):
            probability = None
        if probability is not None:
            item["probability"] = probability
        result.append(item)
    # Equal timestamps are common in whisper.cpp token output. Their source
    # order carries lexical meaning, so neither text nor end time is a tie-break.
    result.sort(key=lambda item: item["start"])
    return result


def normalize_segments(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return validated, ordered transcript/subtitle segments without mutating input.

    Optional Whisper word timestamps are preserved as presentation-neutral timing
    metadata. Subtitle renderers simply ignore the extra field.
    """
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            start = max(0.0, float(raw.get("start", 0.0)))
            end = max(start, float(raw.get("end", start)))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        key = (round(start * 1000), round(end * 1000), text)
        # Two instantaneous fragments can be distinct occurrences of the same
        # word. A zero-duration timestamp is not an identity for deduplication.
        if end > start and key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {"start": start, "end": end, "text": text}
        words = _normalize_words(
            raw.get("words"),
            segment_start=start,
            segment_end=end,
        )
        if words:
            item["words"] = words
        for key in ("quality_issues", "quality_recovery"):
            if key in raw:
                item[key] = raw[key]
        result.append(item)
    result.sort(key=lambda item: item["start"])
    return result


def render_srt(segments: Iterable[dict[str, Any]]) -> str:
    normalized = normalize_segments(segments)
    blocks: list[str] = []
    for index, segment in enumerate(normalized, start=1):
        blocks.append(
            f"{index}\n"
            f"{_timestamp(segment['start'])} --> "
            f"{_timestamp(segment['end'])}\n"
            f"{segment['text']}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_export(
    *,
    text: str,
    segments: Iterable[dict[str, Any]],
    format_name: str,
) -> str:
    fmt = str(format_name or "txt").strip().lower().lstrip(".")
    if fmt == "txt":
        value = str(text or "")
        return value + ("\n" if value and not value.endswith("\n") else "")
    normalized = normalize_segments(segments)
    if not normalized:
        raise ValueError("La sessione non contiene segmenti temporizzati")
    if fmt == "srt":
        return render_srt(normalized)
    raise ValueError(f"formato export non supportato: {format_name}")
