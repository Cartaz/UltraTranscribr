"""Timestamp-preserving transcript export helpers."""
from __future__ import annotations

from typing import Any, Iterable


def _timestamp(seconds: float, *, vtt: bool) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def normalize_segments(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return validated, ordered subtitle segments without mutating input."""
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
        key = (round(start * 1000), round(end * 1000), text)
        if key in seen:
            continue
        seen.add(key)
        result.append({"start": start, "end": end, "text": text})
    result.sort(key=lambda item: (item["start"], item["end"], item["text"]))
    return result


def render_srt(segments: Iterable[dict[str, Any]]) -> str:
    normalized = normalize_segments(segments)
    blocks: list[str] = []
    for index, segment in enumerate(normalized, start=1):
        blocks.append(
            f"{index}\n"
            f"{_timestamp(segment['start'], vtt=False)} --> "
            f"{_timestamp(segment['end'], vtt=False)}\n"
            f"{segment['text']}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_vtt(segments: Iterable[dict[str, Any]]) -> str:
    normalized = normalize_segments(segments)
    blocks = ["WEBVTT"]
    for segment in normalized:
        blocks.append(
            f"{_timestamp(segment['start'], vtt=True)} --> "
            f"{_timestamp(segment['end'], vtt=True)}\n"
            f"{segment['text']}"
        )
    return "\n\n".join(blocks) + "\n"


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
    if fmt == "vtt":
        return render_vtt(normalized)
    raise ValueError(f"formato export non supportato: {format_name}")
