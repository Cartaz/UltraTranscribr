"""Deterministic transcript post-processing profiles.

Profiles return derived text only. The caller is responsible for storing the
result separately from the raw transcript.
"""
from __future__ import annotations

import re


PROFILES: dict[str, str] = {
    "clean": "Pulizia spazi",
    "paragraphs": "Paragrafi leggibili",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def profile_choices() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in PROFILES.items()]


def process_text(text: str, profile: str) -> str:
    raw = str(text or "").strip()
    key = str(profile or "").strip().lower()
    if key not in PROFILES:
        raise ValueError(f"profilo post-processing non supportato: {profile}")
    if not raw:
        return ""

    cleaned = " ".join(raw.split())
    if key == "clean":
        return cleaned

    sentences = [item.strip() for item in _SENTENCE_SPLIT.split(cleaned) if item.strip()]
    if not sentences:
        return cleaned
    paragraphs = [" ".join(sentences[i:i + 3]) for i in range(0, len(sentences), 3)]
    return "\n\n".join(paragraphs)
