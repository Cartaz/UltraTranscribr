# core/text_dedup.py
"""Deduplicazione anti-allucinazione del testo trascritto.

Whisper talvolta produce ripetizioni consecutive di frasi (loop)
e allucinazioni ricorrenti durante il silenzio. Questo modulo
fornisce la logica di deduplicazione separata dal thread
transcriber per rispettare il limite di 300 righe.

Funzioni:
    deduplicate_text: Rimuove ripetizioni consecutive dal testo.
    strip_hallucinations: Rimuove pattern di allucinazione comuni.
"""

from __future__ import annotations

# Pattern di allucinazione comuni di Whisper durante il silenzio.
# Queste frasi vengono generate quando il modello "inventa" testo
# su audio silenzioso o con rumore di fondo. Sono tipiche di vari
# linguaggi e contesti (video, presentazioni, ecc.).
# La chiave e il pattern (lowercase, senza punteggiatura) e il
# valore e la lingua per riferimento.
_HALLUCINATION_PATTERNS: dict[str, str] = {
    # Italiano
    "grazie a tutti": "it",
    "grazie mille": "it",
    "ciao ciao": "it",
    "buonasera": "it",
    "buongiorno": "it",
    "arrivederci": "it",
    # Inglese
    "thank you": "en",
    "thank you for watching": "en",
    "thanks for watching": "en",
    "subscribe to my channel": "en",
    "please subscribe": "en",
    "like and subscribe": "en",
    "thanks for listening": "en",
    "have a great day": "en",
    "see you next time": "en",
    "bye bye": "en",
    "good night": "en",
    # Francese
    "merci beaucoup": "fr",
    "au revoir": "fr",
    "bonsoir": "fr",
    # Spagnolo
    "gracias a todos": "es",
    "muchas gracias": "es",
    "buenas noches": "es",
    # Tedesco
    "vielen dank": "de",
    "auf wiedersehen": "de",
    "guten tag": "de",
    # Portoghese
    "obrigado": "pt",
    "muito obrigado": "pt",
}


def strip_hallucinations(text: str) -> str:
    """Rimuove pattern di allucinazione comuni dal testo.

    Whisper produce spesso le stesse frasi quando trascrive
    silenzio o rumore di fondo. Questa funzione rileva e rimuove
    le frasi allucinatorie piu comuni in vari linguaggi.

    La logica e semplice: se l'intero testo (normalizzato) corrisponde
    a un pattern di allucinazione noto, oppure se il testo e composto
    dalla ripetizione dello stesso pattern, viene restituita stringa
    vuota. Se il pattern appare alla fine del testo, viene rimosso.

    Args:
        text: Testo potenzialmente con allucinazioni.

    Returns:
        Testo con allucinazioni rimosse, o stringa vuota se tutto
        il testo e un'allucinazione.
    """
    if not text.strip():
        return text

    # Normalizza: lowercase, rimuovi punteggiatura
    normalized = _normalize_for_matching(text)

    # Caso 1: tutto il testo e un'allucinazione (o una ripetizione)
    if _is_pure_hallucination(normalized):
        return ""

    # Caso 2: allucinazione alla fine del testo (pattern comune:
    # testo reale seguito da "grazie a tutti grazie a tutti")
    cleaned = _remove_trailing_hallucination(text, normalized)
    return cleaned


def deduplicate_text(text: str) -> str:
    """Rimuove ripetizioni consecutive di frasi causate da allucinazioni Whisper.

    Whisper a volte genera loop sulle ultime parole, es.:
        "by the end of the day I think by the end of the day I think"
    Questo metodo rileva e rimuove tali ripetizioni preservando
    parole ripetute legittime ("that that", "had had", ecc.).

    Prima applica la rimozione di pattern di allucinazione comuni
    (strip_hallucinations), poi la deduplicazione di frasi ripetute.

    Strategia:
      - Prova lunghezze di frase decrescenti (da 15 a 3 parole)
      - Se una frase di N parole e seguita dalla stessa, rimuove il duplicato
      - Esegue piu passate per gestire ripetizioni annidate

    Args:
        text: Testo potenzialmente con ripetizioni.

    Returns:
        Testo con ripetizioni rimosse.
    """
    # Prima passa: rimuovi allucinazioni note
    text = strip_hallucinations(text)
    if not text.strip():
        return ""

    # Seconda passa: deduplicazione frasi ripetute (con punteggiatura)
    words = text.split()
    if len(words) < 6:
        return text

    result = list(words)
    changed = True
    max_passes = 3
    passes = 0

    while changed and passes < max_passes:
        changed = False
        passes += 1
        max_phrase_len = min(15, len(result) // 2)

        for phrase_len in range(max_phrase_len, 2, -1):
            i = 0
            while i <= len(result) - phrase_len * 2:
                phrase = _strip_punctuation_words(result[i:i + phrase_len])
                next_phrase = _strip_punctuation_words(result[i + phrase_len:i + phrase_len * 2])
                if phrase and phrase == next_phrase:
                    result = result[:i + phrase_len] + result[i + phrase_len * 2:]
                    changed = True
                else:
                    i += 1

    return " ".join(result)


def _normalize_for_matching(text: str) -> str:
    """Normalizza il testo per il confronto con i pattern di allucinazione.

    Rimuove punteggiatura e converte in minuscolo.

    Args:
        text: Testo da normalizzare.

    Returns:
        Testo normalizzato.
    """
    # Rimuovi punteggiatura comune
    chars_to_remove = ".,;:!?-'\"()[]{}"
    for ch in chars_to_remove:
        text = text.replace(ch, " ")
    # Normalizza spazi
    return " ".join(text.lower().split())


def _is_pure_hallucination(normalized: str) -> bool:
    """Verifica se il testo normalizzato e un'allucinazione pura.

    Un testo e considerato pura allucinazione se corrisponde
    esattamente a un pattern noto, oppure se e composto dalla
    ripetizione dello stesso pattern (es. "grazie a tutti grazie a
    tutti grazie a tutti").

    Args:
        normalized: Testo normalizzato (lowercase, senza punteggiatura).

    Returns:
        True se il testo e un'allucinazione.
    """
    words = normalized.split()
    if not words:
        return False

    # Controlla se il testo corrisponde a un pattern noto
    for pattern in _HALLUCINATION_PATTERNS:
        if normalized == pattern:
            return True

    # Controlla se il testo e una ripetizione di un pattern noto
    # (es. "grazie a tutti grazie a tutti grazie a tutti")
    for pattern in _HALLUCINATION_PATTERNS:
        pattern_words = pattern.split()
        pat_len = len(pattern_words)
        if pat_len == 0 or len(words) % pat_len != 0:
            continue
        # Verifica che ogni blocco di parole corrisponda al pattern
        is_repetition = True
        for i in range(0, len(words), pat_len):
            chunk = words[i:i + pat_len]
            if chunk != pattern_words:
                is_repetition = False
                break
        if is_repetition and len(words) >= pat_len * 2:
            return True

    # Controlla anche ripetizioni generiche (stessa frase ripetuta 3+ volte)
    # che non corrispondono a pattern noti ma sono chiaramente allucinazioni
    for phrase_len in range(min(8, len(words) // 3), 2, -1):
        if len(words) < phrase_len * 3:
            continue
        phrase = words[:phrase_len]
        repetitions = 0
        for i in range(0, len(words) - phrase_len + 1, phrase_len):
            if words[i:i + phrase_len] == phrase:
                repetitions += 1
            else:
                break
        if repetitions >= 3:
            return True

    return False


def _remove_trailing_hallucination(original: str, normalized: str) -> str:
    """Rimuove allucinazioni in coda al testo.

    Se le ultime parole del testo corrispondono a un pattern di
    allucinazione noto, le rimuove preservando il testo reale che
    le precede.

    Args:
        original: Testo originale con maiuscole e punteggiatura.
        normalized: Testo normalizzato per il confronto.

    Returns:
        Testo con allucinazione finale rimossa.
    """
    norm_words = normalized.split()
    orig_words = original.split()

    # Controlla se le ultime parole corrispondono a un pattern noto
    for pattern in _HALLUCINATION_PATTERNS:
        pattern_words = pattern.split()
        pat_len = len(pattern_words)
        if len(norm_words) < pat_len:
            continue

        # Controlla quante volte il pattern appare alla fine
        # (es. "testo reale grazie a tutti grazie a tutti")
        tail_match_count = 0
        remaining = norm_words[:]
        while len(remaining) >= pat_len and remaining[-pat_len:] == pattern_words:
            tail_match_count += 1
            remaining = remaining[:-pat_len]

        if tail_match_count > 0 and len(remaining) > 0:
            # Rimuovi le parole corrispondenti dal testo originale
            words_to_keep = len(remaining)
            cleaned = " ".join(orig_words[:words_to_keep])
            # Rimuovi punteggiatura orfana alla fine
            cleaned = cleaned.rstrip(".,;:!? ")
            if cleaned:
                return cleaned

    return original


def _strip_punctuation_words(words: list[str]) -> list[str]:
    """Rimuove la punteggiatura dalle parole per il confronto.

    Permette di rilevare ripetizioni anche quando la punteggiatura
    differisce leggermente (es. "grazie a tutti." vs "grazie a tutti,").

    Args:
        words: Lista di parole con eventuale punteggiatura.

    Returns:
        Lista di parole senza punteggiatura, in minuscolo.
    """
    result = []
    for w in words:
        cleaned = w.strip(".,;:!?'\"()[]{}").lower()
        if cleaned:
            result.append(cleaned)
    return result
