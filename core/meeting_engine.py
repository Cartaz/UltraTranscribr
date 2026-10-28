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
