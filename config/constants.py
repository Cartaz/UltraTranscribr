"""Costanti globali di UltraTranscribr."""
from __future__ import annotations

import os
from pathlib import Path


def _xdg_config_home() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_cache_home() -> Path:
    return Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))


def _xdg_data_home() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))


class AppMeta:
    NAME = "UltraTranscribr"
    VERSION = "5.5.0"
    ID = "com.ultratranscribr.app"
    CONFIG_DIR = _xdg_config_home() / "ultratranscribr"
    SETTINGS_PATH = CONFIG_DIR / "settings.json"
    LOG_PATH = CONFIG_DIR / "ultratranscribr.log"
    DATA_DIR = _xdg_data_home() / "ultratranscribr"
    TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
    RECORDINGS_DIR = DATA_DIR / "recordings"
    CACHE_DIR = _xdg_cache_home() / "ultratranscribr"
    MODELS_DIR = CACHE_DIR / "models" / "gguf"
    DIARIZATION_MODELS_DIR = CACHE_DIR / "models" / "diarization"
    DICTATION_METRICS_PATH = DATA_DIR / "dictation-metrics.jsonl"
    DICTATION_PORTAL_STATE_PATH = CONFIG_DIR / "dictation-portal.json"


class ProcessDefaults:
    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_MS = 3000
    DTYPE = "float32"
    MODEL_SIZE = "large-v3"
    LANGUAGE = "en"
    # Greedy decoding: on the Meteor Lake iGPU any beam > 1 costs ~2.2x (beams
    # 2-5 cost the same) with no measurable WER gain on Italian FLEURS, and
    # beam 5 cannot keep real time in Live with large-v3.
    BEAM_SIZE = 1
    VAD_FILTER = True
    VAD_MIN_SILENCE_MS = 500
    BUFFER_WARN_THRESHOLD = 20
    HISTORY_RETENTION_DAYS = 90
    MEETING_AUDIO_RETENTION_DAYS = 30
    BUFFER_MAX_MEMORY_CHUNKS = 120
    SINK_SEARCH_KEYWORD = ""
    LEGACY_FIREFOX_KEYWORD = "Firefox"
    RECONNECT_DELAY = 2.0
    MAX_RECONNECT_ATTEMPTS = 5
    OVERLAP_DURATION_S = 2.0
    SEGMENT_LENGTH_S = 10.0
    MIN_SEGMENT_S = 2.0
    FILE_SEGMENT_LENGTH_S = 30.0
    FILE_OVERLAP_DURATION_S = 2.0
    SILENCE_RMS_THRESHOLD = 0.005
    TRANSCRIBE_RETRY_DELAY_S = 2.0


class DictationDefaults:
    """Initial low-latency profile; tune from measured KDE/Wayland runs."""

    CAPTURE_CHUNK_MS = 250
    STEP_MS = 750
    # Whisper always encodes 30 s, so a long window costs no more encoder time;
    # decoding grows with its words (Meteor Lake iGPU, beam 1: ~4 s per
    # request at 5 s of speech, 5-7 s at 20-25 s). The window grows from the
    # first word; from this length it is committed up to the last Whisper
    # segment boundary and restarted from there. With no boundary it keeps
    # growing and is closed whole at WINDOW_HARD_CAP_MS, under Whisper's 30 s.
    WINDOW_MS = 25000
    WINDOW_HARD_CAP_MS = 29000
    MIN_AUDIO_MS = 1000
    REQUEST_TIMEOUT_S = 60.0
    PROMPT_CHARS = 500
    SCHEDULER_AGING_S = 30.0


class SYCLDefaults:
    ONEAPI_DEVICE_SELECTOR = "level_zero:0"
    PORT = 8082
    HOST = "127.0.0.1"
    HEALTH_TIMEOUT_S = 90.0
    HEALTH_POLL_INTERVAL_S = 0.5
    LIVE_REQUEST_TIMEOUT_S = 180.0
    FILE_CHUNK_REQUEST_TIMEOUT_S = 600.0
    VAD_THRESHOLD = 0.5


class WhisperServerDefaults:
    MODEL_REPO_ID = "ggerganov/whisper.cpp"
    MODEL_REPO_FALLBACK = "ggml-org/whisper-large-v3-turbo"
    VAD_REPO_ID = "ggml-org/whisper-vad"
    VAD_MODEL_FILENAME = "ggml-silero-v6.2.0.bin"
    SERVER_BINARY_NAME = "whisper-server"


class UIConstraints:
    MIN_WINDOW_WIDTH = 1200
    MIN_WINDOW_HEIGHT = 800
    WINDOW_WIDTH = MIN_WINDOW_WIDTH
    WINDOW_HEIGHT = MIN_WINDOW_HEIGHT
