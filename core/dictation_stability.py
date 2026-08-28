"""Stable-prefix commit logic for revisable streaming Whisper hypotheses."""
from __future__ import annotations

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


def _overlap_length(committed: list[str], candidate: list[str]) -> int:
    limit = min(len(committed), len(candidate))
    for size in range(limit, 0, -1):
        if committed[-size:] == candidate[:size]:
            return size
    return 0


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

    @property
    def committed_text(self) -> str:
        return " ".join(self._committed)

    @property
    def pending_text(self) -> str:
        return " ".join(self._current_pending)

    def update(self, hypothesis: str) -> StablePrefixUpdate:
        candidate = _tokens(hypothesis)
        overlap = _overlap_length(self._committed, candidate)
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
