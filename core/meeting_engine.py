"""Language policy shared by meeting jobs, workers and the queue."""

# The CTC model is English-only. Other supported languages use Qwen's
# multilingual forced aligner, without feeding Italian words to English CTC.
ALIGNMENT_LANGUAGES = {
    "en": "English", "it": "Italian", "fr": "French", "de": "German",
    "es": "Spanish", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese",
}
QWEN_PIPELINES = {"qwen_meeting", "english_qwen"}
DEFAULT_MEETING_PIPELINE = "qwen_meeting"


class MeetingEngineStillRunning(RuntimeError):
    """A child process survived shutdown; keep Whisper from loading over it."""


def meeting_language(value: str) -> str:
    language = str(value or "").strip().lower().split("-")[0]
    if language not in ALIGNMENT_LANGUAGES:
        raise ValueError("Scegli una lingua supportata per la riunione: "
                         + ", ".join(ALIGNMENT_LANGUAGES))
    return language


def speaker_count(value) -> int:
    """Validate UI/batch counts without silently truncating a fraction."""
    import math
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Il numero di interlocutori deve essere un intero tra 0 e 20") from exc
    if isinstance(value, bool) or not math.isfinite(number) or not number.is_integer() or not 0 <= number <= 20:
        raise ValueError("Il numero di interlocutori deve essere un intero tra 0 e 20")
    return int(number)
