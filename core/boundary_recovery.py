"""Conservative experimental recovery of words discarded at chunk boundaries."""
import math
import re
import unicodedata
from difflib import SequenceMatcher

from core.word_timing import lexical_words


def _canonical(word):
    word = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in word if c.isalnum() and not unicodedata.combining(c))


def recover_boundary(raw_segments, history, offset, cutoff, minimum_probability=0.8):
    """Return an approximate-timing segment, or no recovery without evidence.

    History and cutoff must belong to the outer audio timeline, never to the
    shorter windows used for retrying a failed recognition.
    """
    if offset <= 0 or cutoff <= offset or not history:
        return []
    prefix = []
    for segment in raw_segments:
        # A nested recovery has synthetic timestamps and must not be treated
        # as fresh acoustic evidence for another boundary recovery.
        if (segment.get("quality_recovery") or {}).get("timing_requires_review"):
            break
        words, _ = lexical_words(str(segment.get("text") or ""), segment.get("words", []))
        if not words:
            break
        prefix.extend(w for w in words if offset + w["end"] <= cutoff + 0.001)
        if any(offset + w["end"] > cutoff + 0.001 for w in words):
            break
    tail = []
    for segment in history:
        if segment["end"] < offset - 1:
            continue
        words, _ = lexical_words(segment["text"], segment.get("words", []))
        if words:
            tail.extend(w["word"] for w in words if w["end"] >= offset - 1)
        else:
            tail.extend(re.findall(r"\S+", segment["text"]))
    previous = [_canonical(w) for w in tail[-32:]]
    incoming = [_canonical(w["word"]) for w in prefix]
    matching = SequenceMatcher(a=previous, b=incoming, autojunk=False).get_matching_blocks()
    duplicate_end = max((m.b + m.size for m in matching if m.size >= 2), default=0)
    novel = prefix[duplicate_end:]
    if len(novel) == 1 and _canonical(novel[0]["word"]) in previous:
        novel = []
    try:
        probability = sum(float(w.get("probability") or 0) for w in novel) / max(1, len(novel))
    except (TypeError, ValueError):
        return []
    if not novel or not math.isfinite(probability) or probability < minimum_probability:
        return []
    text = "".join(w["word"] for w in novel).strip()
    local = cutoff - offset
    words = [{"word": w["word"], "start": local, "end": local + .01,
                  "probability": w.get("probability")} for w in novel]
    evidence = {"reason": "overlap_boundary_recovered", "text": text,
                    "original_audio_start": offset + novel[0]["start"],
                    "original_audio_end": offset + novel[-1]["end"],
                    "timing_requires_review": True, "mean_probability": probability}
    return [{"start": local, "end": local + .01, "text": text, "words": words,
                 "quality_recovery": evidence}]
