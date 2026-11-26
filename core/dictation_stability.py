"""Stable-prefix commit logic for revisable streaming Whisper hypotheses."""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.text_dedup import deduplicate_text


def _tokens(text: str) -> list[str]:
    return deduplicate_text(str(text or "")).strip().split()


def _common_prefix_length(left: list[str], right: list[str]) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _comparable(word: str) -> str:
    return re.sub(r"[^\w]", "", word.casefold())


def _overlap_length(committed: list[str], candidate: list[str], *, strict: bool = False) -> int:
    """Return how many leading candidate words re-transcribe committed audio.

    Every hypothesis of a segment starts again from the segment's first
    word, so the committed segment words are a prefix of the candidate up to
    Whisper's small rewrites ("perché" vs "perchè", a word added or dropped).
    Pick the candidate prefix closest to them by word edit distance, looking
    only a few words past their length so that a common word later in the
    new speech cannot swallow the words before it. With ``strict``, a
    candidate that does not resemble the committed words at all (Whisper
    skipped them) overlaps nothing, so its words are not silently dropped.
    """
    if not committed or not candidate:
        return 0
    left = [_comparable(word) for word in committed]
    right = [_comparable(word) for word in candidate]
    slack = max(3, len(left) // 5)
    limit = min(len(right), len(left) + slack)
    # distances[k] = edit distance between committed and candidate[:k].
    distances = list(range(limit + 1))
    for i, word in enumerate(left, start=1):
        previous, distances[0] = distances[0], i
        for k in range(1, limit + 1):
            previous, distances[k] = distances[k], min(
                distances[k] + 1,
                distances[k - 1] + 1,
                previous + (word != right[k - 1]),
            )
    best = min(range(limit + 1), key=lambda k: (distances[k], abs(k - len(left)), -k))
    if strict:
        # Words the candidate is too short to contain are unavoidable edits.
        unavoidable = max(0, len(left) - limit)
        if distances[best] - unavoidable > (len(left) - unavoidable) // 2:
            return 0
    return best


@dataclass(frozen=True)
class StablePrefixUpdate:
    committed_delta: str
    committed_text: str
    pending_text: str
    hypothesis: str


class StablePrefixCommitter:
    """Commit only words stable across two consecutive hypotheses."""

    def __init__(self) -> None:
        self._committed: list[str] = []
        self._previous_pending: list[str] = []
        self._current_pending: list[str] = []
        self._segment_start = 0

    @property
    def committed_text(self) -> str:
        return " ".join(self._committed)

    @property
    def context_text(self) -> str:
        """Text of earlier segments: the prompt for the current segment.

        The current segment's own words must stay out of the prompt, since
        its audio is transcribed again; Whisper tends to skip speech it
        already finds in the prompt.
        """
        return " ".join(self._committed[: self._segment_start])

    @property
    def segment_is_empty(self) -> bool:
        """True while the current segment has produced no text yet."""
        return len(self._committed) == self._segment_start and not self._current_pending

    @property
    def pending_text(self) -> str:
        return " ".join(self._current_pending)

    def update(self, hypothesis: str) -> StablePrefixUpdate:
        candidate = _tokens(hypothesis)
        # Only words committed from the current audio segment can reappear
        # at the start of its hypotheses; older segments' audio is gone.
        overlap = _overlap_length(self._committed[self._segment_start:], candidate, strict=True)
        pending = candidate[overlap:]
        stable_count = _common_prefix_length(self._previous_pending, pending)
        delta_words = pending[:stable_count]
        if delta_words:
            self._committed.extend(delta_words)
        self._previous_pending = pending[stable_count:]
        self._current_pending = pending[stable_count:]
        return StablePrefixUpdate(
            committed_delta=" ".join(delta_words),
            committed_text=self.committed_text,
            pending_text=self.pending_text,
            hypothesis=" ".join(candidate),
        )

    def close_segment(self, head_hypothesis: str) -> StablePrefixUpdate:
        """Commit the segment's audio up to a cut and start a new segment there.

        ``head_hypothesis`` is the part of the latest hypothesis before the
        cut. Words this segment already committed beyond it came from audio
        after the cut, which the next segment transcribes again, so they stay
        committed but become the start of the new segment instead of being
        typed twice.
        """
        head = _tokens(head_hypothesis)
        segment = self._committed[self._segment_start:]
        covered = _overlap_length(head, segment)
        delta_words: list[str] = []
        carried = len(segment) - covered
        if not carried:
            delta_words = head[_overlap_length(segment, head):]
            self._committed.extend(delta_words)
        self._segment_start = len(self._committed) - carried
        self._previous_pending = []
        self._current_pending = []
        return StablePrefixUpdate(
            committed_delta=" ".join(delta_words),
            committed_text=self.committed_text,
            pending_text="",
            hypothesis=" ".join(head),
        )

    def finalize(self) -> StablePrefixUpdate:
        delta_words = list(self._current_pending)
        if delta_words:
            self._committed.extend(delta_words)
        self._previous_pending = []
        self._current_pending = []
        return StablePrefixUpdate(
            committed_delta=" ".join(delta_words),
            committed_text=self.committed_text,
            pending_text="",
            hypothesis=self.committed_text,
        )
