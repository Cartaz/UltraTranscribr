"""Reconcile Whisper timing with speaker diarization for Meeting review.

This module is deliberately independent of Qt, audio decoding and model
inference. It turns persisted timing into review segments, keeps manual edits
separate from automatic assignments, and exposes deterministic speaker-ID
stabilization for diarization reruns.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Optional

from core.transcript_export import normalize_segments
from core.word_timing import lexical_words

_UNCERTAINTY_RATIO = 0.8
_POINT_WINDOW_S = 0.04
_OVERLAP_EPSILON_S = 0.03
_SCORE_PRECISION = 9
_MAX_CONTINUITY_GAP_S = 0.6


def align_speakers(
    transcript_segments: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
    speaker_diarization_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Create editable review segments from Whisper + Community-1 timing.

    New transcripts carrying Whisper word timestamps are split at speaker
    hand-offs inside a single Whisper segment. Older transcripts without word
    timing retain the historical segment-level alignment. Regular (non-
    exclusive) diarization is optional and is used only to flag true overlapping
    speech; exclusive diarization remains the source for text assignment.
    """
    transcript = normalize_segments(transcript_segments)
    exclusive = _valid_diarization_segments(diarization_segments)
    regular = _valid_diarization_segments(speaker_diarization_segments or [])
    output: list[dict[str, Any]] = []

    for source_index, segment in enumerate(transcript):
        words = list(segment.get("words") or [])
        warnings = []
        if words:
            words, warnings = lexical_words(str(segment["text"]), words)
            aligned = _align_word_segment(
                source_index,
                segment,
                words,
                exclusive,
                regular,
            )
            if aligned:
                for row in aligned:
                    if segment.get("quality_issues"):
                        row["quality_issues"] = segment["quality_issues"]
                output.extend(aligned)
                continue
        row = _align_whisper_segment(
            source_index,
            segment,
            exclusive,
            regular,
        )
        if warnings:
            row["alignment_warnings"] = warnings
        if segment.get("quality_issues"):
            row["quality_issues"] = segment["quality_issues"]
        output.append(row)
    return output


def _align_word_segment(
    source_index: int,
    segment: dict[str, Any],
    words: list[dict[str, Any]],
    exclusive: list[dict[str, Any]],
    regular: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assigned: list[dict[str, Any]] = []
    for word_index, word in enumerate(words):
        text = str(word.get("word") or "")
        if not text.strip():
            continue
        try:
            start = float(word.get("start", segment["start"]))
            end = max(start, float(word.get("end", start)))
        except (TypeError, ValueError):
            continue
        speaker_id, uncertain, candidates = _assign_interval(start, end, exclusive)
        warnings = []
        if not candidates:
            continued = _continuity_speaker(start, end, exclusive, regular)
            if continued:
                speaker_id, uncertain, candidates = continued, False, [continued]
                warnings.append("diarization_gap_bridged")
        if not speaker_id:
            warnings.append(
                "ambiguous_speakers" if candidates else "no_speaker_coverage"
            )
        assigned.append(
            {
                "word_index": word.get("source_word_start", word_index),
                "word_end": word.get("source_word_end", word_index + 1),
                "word": text,
                "start": start,
                "end": end,
                "speaker_id": speaker_id,
                "uncertain": uncertain,
                "speaker_candidates": candidates,
                "alignment_warnings": warnings,
            }
        )

    if not assigned:
        return []

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_key: tuple[Any, ...] | None = None
    for word in assigned:
        key = _word_group_key(word)
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(word)
        current_key = key
    if current:
        groups.append(current)

    output: list[dict[str, Any]] = []
    for group in groups:
        raw_text = "".join(str(word["word"]) for word in group).strip()
        if not raw_text:
            continue
        start = float(group[0]["start"])
        end = max(start, float(group[-1]["end"]))
        row: dict[str, Any] = {
            "start": start,
            "end": end,
            "raw_text": raw_text,
            "text": raw_text,
            "speaker_id": group[0]["speaker_id"],
            "uncertain": bool(group[0]["uncertain"]),
            "speaker_candidates": _group_candidates(group),
            "alignment": "word",
            "source_segment_index": int(source_index),
            "source_word_start": int(group[0]["word_index"]),
            "source_word_end": int(group[-1]["word_end"]),
        }
        warnings = sorted(
            {reason for word in group for reason in word["alignment_warnings"]}
        )
        if warnings:
            row["alignment_warnings"] = warnings
        overlap_speakers = _true_overlap_speakers(start, end, regular)
        if overlap_speakers:
            row["overlap_speakers"] = overlap_speakers
        output.append(row)
    return output


def _word_group_key(word: dict[str, Any]) -> tuple[Any, ...]:
    """Group by the decision that matters, not by noisy secondary candidates."""
    if bool(word.get("uncertain")):
        return (
            "uncertain",
            tuple(sorted(str(item) for item in word.get("speaker_candidates") or [])),
        )
    return ("speaker", word.get("speaker_id"))


def _group_candidates(group: list[dict[str, Any]]) -> list[str]:
    """Return deterministic candidate metadata without influencing segmentation."""
    candidates: set[str] = set()
    primary = str(group[0].get("speaker_id") or "")
    for word in group:
        candidates.update(
            str(item)
            for item in word.get("speaker_candidates") or []
            if str(item)
        )
    ordered = sorted(candidates)
    if primary and primary in ordered:
        ordered.remove(primary)
        ordered.insert(0, primary)
    return ordered[:2]


def _align_whisper_segment(
    source_index: int,
    segment: dict[str, Any],
    exclusive: list[dict[str, Any]],
    regular: list[dict[str, Any]],
) -> dict[str, Any]:
    start = float(segment["start"])
    end = float(segment["end"])
    speaker_id, uncertain, candidates = _assign_interval(start, end, exclusive)
    text = str(segment.get("text") or "").strip()
    row: dict[str, Any] = {
        "start": start,
        "end": end,
        "raw_text": text,
        "text": text,
        "speaker_id": speaker_id,
        "uncertain": uncertain,
        "speaker_candidates": candidates,
        "alignment": "segment",
        "source_segment_index": int(source_index),
    }
    overlap_speakers = _true_overlap_speakers(start, end, regular)
    if overlap_speakers:
        row["overlap_speakers"] = overlap_speakers
    return row


def _assign_interval(
    start: float,
    end: float,
    diarization: list[dict[str, Any]],
) -> tuple[str | None, bool, list[str]]:
    probe_start = max(0.0, float(start))
    probe_end = max(probe_start, float(end))
    if probe_end - probe_start < _POINT_WINDOW_S:
        midpoint = (probe_start + probe_end) / 2.0
        probe_start = max(0.0, midpoint - _POINT_WINDOW_S / 2.0)
        probe_end = midpoint + _POINT_WINDOW_S / 2.0

    overlaps: dict[str, float] = defaultdict(float)
    for turn in diarization:
        overlap = max(
            0.0,
            min(probe_end, float(turn["end"])) - max(probe_start, float(turn["start"])),
        )
        if overlap > 0:
            overlaps[str(turn["speaker_id"])] += overlap

    ranked = sorted(
        overlaps.items(),
        key=lambda item: (-round(item[1], _SCORE_PRECISION), item[0]),
    )
    candidates = [speaker for speaker, _score in ranked[:2]]
    if not ranked:
        return None, True, candidates
    best_score = round(ranked[0][1], _SCORE_PRECISION)
    second_score = round(ranked[1][1], _SCORE_PRECISION) if len(ranked) > 1 else 0.0
    uncertain = (
        len(ranked) > 1
        and best_score > 0
        and second_score / best_score >= _UNCERTAINTY_RATIO
    )
    return (None if uncertain else ranked[0][0]), uncertain, candidates


def _true_overlap_speakers(
    start: float,
    end: float,
    regular: list[dict[str, Any]],
) -> list[str]:
    """Return speakers that actually overlap one another inside the interval."""
    relevant = [
        turn
        for turn in regular
        if min(float(end), float(turn["end"]))
        - max(float(start), float(turn["start"]))
        > _OVERLAP_EPSILON_S
    ]
    overlapping: set[str] = set()
    for index, left in enumerate(relevant):
        for right in relevant[index + 1 :]:
            if left["speaker_id"] == right["speaker_id"]:
                continue
            overlap = (
                min(float(end), float(left["end"]), float(right["end"]))
                - max(float(start), float(left["start"]), float(right["start"]))
            )
            if overlap > _OVERLAP_EPSILON_S:
                overlapping.add(str(left["speaker_id"]))
                overlapping.add(str(right["speaker_id"]))
    return sorted(overlapping)


def build_speaker_id_mapping(
    previous_segments: list[dict[str, Any]],
    new_segments: list[dict[str, Any]],
) -> dict[str, str]:
    """Map new cluster labels onto prior stable IDs by temporal overlap."""
    previous = _valid_diarization_segments(previous_segments)
    current = _valid_diarization_segments(new_segments)
    if not current:
        return {}
    if not previous:
        return {speaker: speaker for speaker in sorted({row["speaker_id"] for row in current})}

    scores: dict[tuple[str, str], float] = defaultdict(float)
    old_ids = {item["speaker_id"] for item in previous}
    new_ids = {item["speaker_id"] for item in current}
    for new in current:
        for old in previous:
            overlap = max(
                0.0,
                min(float(new["end"]), float(old["end"]))
                - max(float(new["start"]), float(old["start"])),
            )
            if overlap > 0:
                scores[(new["speaker_id"], old["speaker_id"])] += overlap

    mapping: dict[str, str] = {}
    used_old: set[str] = set()
    ranked = sorted(
        (
            (score, new_id, old_id)
            for (new_id, old_id), score in scores.items()
            if score > 0
        ),
        key=lambda item: (-item[0], item[2], item[1]),
    )
    for _score, new_id, old_id in ranked:
        if new_id in mapping or old_id in used_old:
            continue
        mapping[new_id] = old_id
        used_old.add(old_id)

    reserved = set(old_ids)
    next_number = 0
    for new_id in sorted(new_ids):
        if new_id in mapping:
            continue
        while f"SPEAKER_{next_number:02d}" in reserved:
            next_number += 1
        stable = f"SPEAKER_{next_number:02d}"
        mapping[new_id] = stable
        reserved.add(stable)
        next_number += 1
    return mapping


def remap_speaker_ids(
    segments: list[dict[str, Any]],
    mapping: dict[str, str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in segments:
        row = dict(item)
        speaker_id = str(row.get("speaker_id") or "")
        if speaker_id in mapping:
            row["speaker_id"] = mapping[speaker_id]
        output.append(row)
    return output


def stabilize_speaker_ids(
    previous_segments: list[dict[str, Any]],
    new_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return remap_speaker_ids(
        new_segments,
        build_speaker_id_mapping(previous_segments, new_segments),
    )


def preserve_review_edits(
    previous_review: list[dict[str, Any]],
    new_review: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry safe manual text/speaker overrides across a diarization rerun."""
    indexed: dict[tuple[Any, ...], deque[dict[str, Any]]] = defaultdict(deque)
    for item in previous_review:
        indexed[_review_identity(item)].append(item)

    previous_sources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    new_sources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for items, target in (
        (previous_review, previous_sources),
        (new_review, new_sources),
    ):
        for item in items:
            source = item.get("source_segment_index")
            if isinstance(source, int) and source >= 0:
                target[source].append(item)
    protected = {}
    for source, previous in previous_sources.items():
        current = new_sources.get(source)
        if not current:
            continue
        edited = any(
            str(row.get("text") or "") != str(row.get("raw_text") or "")
            or row.get("speaker_override")
            for row in previous
        )
        if edited and (
            [_review_identity(row) for row in previous]
            != [_review_identity(row) for row in current]
        ):
            # A rewritten sentence cannot safely be distributed over newly
            # split words. Retain the author's entire source-segment layout,
            # refresh acoustic decisions, and expose the new raw alternative.
            replacement = []
            for old in previous:
                row = dict(old)
                matches = [new for new in current if _review_ranges_overlap(old, new)]
                speakers = {
                    new.get("speaker_id") for new in matches if new.get("speaker_id")
                }
                certain = (
                    bool(matches)
                    and len(speakers) == 1
                    and all(
                        new.get("speaker_id") and not new.get("uncertain")
                        for new in matches
                    )
                )
                row["speaker_id"] = next(iter(speakers)) if certain else None
                row["uncertain"] = not certain
                row["speaker_candidates"] = sorted(speakers)
                row["alignment_warnings"] = sorted(
                    set(row.get("alignment_warnings") or [])
                    | {"manual_layout_preserved"}
                )
                replacement.append(row)
            replacement[0]["alignment_recovery_text"] = " ".join(
                str(row.get("raw_text") or "") for row in current
            )
            protected[source] = replacement

    output: list[dict[str, Any]] = []
    emitted = set()
    for item in new_review:
        source = item.get("source_segment_index")
        if source in protected:
            if source not in emitted:
                output.extend(protected[source])
                emitted.add(source)
            continue
        row = dict(item)
        bucket = indexed.get(_review_identity(row))
        if bucket:
            previous = bucket.popleft()
            row["text"] = str(previous.get("text") or "")
            override = str(previous.get("speaker_override") or "").strip()
            if override.startswith("SPEAKER_"):
                row["speaker_override"] = override
        output.append(row)
    return output


def preserve_review_text(
    previous_review: list[dict[str, Any]],
    new_review: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Backward-compatible alias for the richer review-edit preservation."""
    return preserve_review_edits(previous_review, new_review)


def effective_speaker_id(item: dict[str, Any]) -> Optional[str]:
    override = str(item.get("speaker_override") or "").strip()
    if override.startswith("SPEAKER_"):
        return override
    automatic = str(item.get("speaker_id") or "").strip()
    return automatic or None


def speaker_label(speaker_id: Optional[str], names: dict[str, str]) -> str:
    if not speaker_id:
        return "Speaker ?"
    custom = str(names.get(speaker_id) or "").strip()
    if custom:
        return custom
    try:
        number = int(str(speaker_id).rsplit("_", 1)[-1]) + 1
    except ValueError:
        return str(speaker_id)
    return f"Speaker {number}"


def _review_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    alignment = str(item.get("alignment") or "")
    try:
        source_index = int(item.get("source_segment_index"))
    except (TypeError, ValueError):
        source_index = -1
    raw = str(item.get("raw_text") or "").strip()
    if alignment == "word" and source_index >= 0:
        try:
            word_start = int(item.get("source_word_start"))
            word_end = int(item.get("source_word_end"))
        except (TypeError, ValueError):
            word_start = word_end = -1
        if word_start >= 0 and word_end > word_start:
            return ("word", source_index, word_start, word_end, raw)
    try:
        start = round(float(item.get("start", 0.0)), 3)
        end = round(float(item.get("end", 0.0)), 3)
    except (TypeError, ValueError):
        start = end = 0.0
    return ("segment", source_index, start, end, raw)


def _valid_diarization_segments(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in segments:
        try:
            start = max(0.0, float(item.get("start", 0.0)))
            end = max(start, float(item.get("end", 0.0)))
        except (TypeError, ValueError):
            continue
        speaker_id = str(item.get("speaker_id") or "").strip()
        if end <= start or not speaker_id:
            continue
        output.append({"start": start, "end": end, "speaker_id": speaker_id})
    output.sort(key=lambda item: (item["start"], item["end"], item["speaker_id"]))
    return output


def _continuity_speaker(start, end, exclusive, regular):
    """Bridge only a small unlabelled gap, never an observed competing voice.

    Equal names in the transcript are insufficient evidence. The surrounding
    acoustic turns must agree and no regular/exclusive turn may contradict
    continuity. An explicit annotation records the inference for review.
    """
    if end <= start or end - start > _MAX_CONTINUITY_GAP_S:
        return None
    left = [turn for turn in exclusive if turn["end"] <= start]
    right = [turn for turn in exclusive if turn["start"] >= end]
    if not left or not right:
        return None
    before = max(left, key=lambda turn: turn["end"])
    after = min(right, key=lambda turn: turn["start"])
    speaker = before["speaker_id"]
    if speaker != after["speaker_id"]:
        return None
    if after["start"] - before["end"] > _MAX_CONTINUITY_GAP_S:
        return None
    if any(
        turn["speaker_id"] != speaker
        and turn["start"] < after["start"]
        and turn["end"] > before["end"]
        for turn in [*exclusive, *regular]
    ):
        return None
    return speaker


def _review_ranges_overlap(left, right):
    if left.get("alignment") == right.get("alignment") == "word":
        return int(left.get("source_word_start", -1)) < int(
            right.get("source_word_end", -1)
        ) and int(right.get("source_word_start", -1)) < int(
            left.get("source_word_end", -1)
        )
    start = max(float(left.get("start", 0)), float(right.get("start", 0)))
    end = min(float(left.get("end", 0)), float(right.get("end", 0)))
    return end >= start
