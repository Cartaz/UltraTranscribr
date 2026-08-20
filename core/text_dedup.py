"""Deduplicazione conservativa del testo Whisper.

Non elimina mai una singola frase comune (es. "Buongiorno" o "Thank you"):
quelle possono essere parlato reale. Le euristiche aggressive sono limitate a
ripetizioni consecutive chiaramente patologiche e possono essere disattivate
per musica/lyrics.
"""
from __future__ import annotations

import re

_PUNCT = ".,;:!?-'\"()[]{}"
_KNOWN_HALLUCINATIONS = {
    "grazie a tutti", "grazie mille", "ciao ciao", "arrivederci",
    "thank you for watching", "thanks for watching", "subscribe to my channel",
    "please subscribe", "like and subscribe", "thanks for listening",
    "see you next time", "merci beaucoup", "au revoir", "gracias a todos",
    "muchas gracias", "vielen dank", "auf wiedersehen", "muito obrigado",
}


def _norm_words(text: str) -> list[str]:
    return [w.strip(_PUNCT).lower() for w in text.split() if w.strip(_PUNCT)]


def strip_hallucinations(text: str) -> str:
    """Rimuove solo pattern noti ripetuti almeno due volte consecutivamente."""
    if not text.strip():
        return text
    words = text.split()
    norm = _norm_words(text)
    for pattern in _KNOWN_HALLUCINATIONS:
        p = pattern.split()
        n = len(p)
        if n == 0 or len(norm) < 2 * n:
            continue
        if len(norm) % n == 0 and len(norm) // n >= 2:
            if all(norm[i:i + n] == p for i in range(0, len(norm), n)):
                return ""
        repeats = 0
        pos = len(norm)
        while pos >= n and norm[pos - n:pos] == p:
            repeats += 1
            pos -= n
        if repeats >= 2 and pos > 0:
            return " ".join(words[:pos]).rstrip(_PUNCT + " ")
    return text


def deduplicate_text(text: str, *, preserve_repetitions: bool = False) -> str:
    """Rimuove loop consecutivi; in modalita musica preserva i ritornelli."""
    text = text.strip()
    if not text:
        return ""
    if preserve_repetitions:
        return re.sub(r"\s+", " ", text).strip()

    text = strip_hallucinations(text)
    if not text:
        return ""
    words = text.split()
    if len(words) < 6:
        return text

    result = words[:]
    for _ in range(3):
        changed = False
        max_len = min(20, len(result) // 2)
        for phrase_len in range(max_len, 3, -1):
            i = 0
            while i + 2 * phrase_len <= len(result):
                a = _norm_words(" ".join(result[i:i + phrase_len]))
                b = _norm_words(" ".join(result[i + phrase_len:i + 2 * phrase_len]))
                if a and a == b:
                    del result[i + phrase_len:i + 2 * phrase_len]
                    changed = True
                else:
                    i += 1
        if not changed:
            break
    return " ".join(result)


def remove_chunk_overlap(previous: str, current: str, *, max_words: int = 40) -> str:
    """Rimuove solo un prefisso corrente identico alla coda precedente."""
    if not previous.strip() or not current.strip():
        return current.strip()
    prev = previous.split()
    cur = current.split()
    max_check = min(max_words, len(prev), len(cur))
    for n in range(max_check, 1, -1):
        if _norm_words(" ".join(prev[-n:])) == _norm_words(" ".join(cur[:n])):
            return " ".join(cur[n:]).strip()
    return current.strip()
