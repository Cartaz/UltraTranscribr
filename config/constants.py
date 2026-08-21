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
    VERSION = "5.3.0"
    ID = "com.ultratranscribr.app"
    DESCRIPTION = "Trascrizione audio accelerata GPU Intel Arc (SYCL)"
    LICENSE = "MIT"
    CONFIG_DIR = _xdg_config_home() / "ultratranscribr"
    SETTINGS_PATH = CONFIG_DIR / "settings.json"
    LOG_PATH = CONFIG_DIR / "ultratranscribr.log"
    DATA_DIR = _xdg_data_home() / "ultratranscribr"
    TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
    DESKTOP_DIR = _xdg_data_home() / "applications"
    CACHE_DIR = _xdg_cache_home() / "ultratranscribr"
    MODELS_DIR = CACHE_DIR / "models" / "gguf"


class ProcessDefaults:
    SAMPLE_RATE = 16000
    CHANNELS = 1
    CHUNK_MS = 3000
    DTYPE = "float32"
    MODEL_SIZE = "large-v3-turbo"
    DEVICE = "sycl"
    COMPUTE_TYPE = "f16"
    LANGUAGE = "en"
    AUDIO_SOURCE = "firefox"
    BEAM_SIZE = 5
    VAD_FILTER = True
    VAD_MIN_SILENCE_MS = 500
    BUFFER_WARN_THRESHOLD = 20
    # Mantiene in RAM ~6 minuti con chunk da 3 s; oltre questa soglia
    # BufferManager fa spill su un file temporaneo preservando l'ordine.
    BUFFER_MAX_MEMORY_CHUNKS = 120
    SINK_SEARCH_KEYWORD_FIREFOX = "Firefox"
    SINK_SEARCH_KEYWORD_MIC = "HDA Intel PCH"
    RECONNECT_DELAY = 2.0
    MAX_RECONNECT_ATTEMPTS = 5
    OVERLAP_DURATION_S = 2.0
    SEGMENT_LENGTH_S = 10.0
    MIN_SEGMENT_S = 2.0
    FILE_SEGMENT_LENGTH_S = 30.0
    FILE_OVERLAP_DURATION_S = 2.0
    SILENCE_RMS_THRESHOLD = 0.005
    TRANSCRIBE_RETRY_DELAY_S = 2.0


class SYCLDefaults:
    ONEAPI_DEVICE_SELECTOR = "level_zero:0"
    GPU_LAYERS = 99
    PORT = 8082
    HOST = "127.0.0.1"
    HEALTH_TIMEOUT_S = 90.0
    HEALTH_POLL_INTERVAL_S = 0.5
    # Il timeout live e volutamente separato da quello file. Le richieste
    # live contengono ~10-12 s di audio e non devono restare bloccate per ore.
    LIVE_REQUEST_TIMEOUT_S = 180.0
    # La trascrizione file e ora segmentata in chunk da 30 s, quindi non usa
    # piu una singola POST lunga ore. Lasciamo comunque margine alle iGPU lente.
    FILE_CHUNK_REQUEST_TIMEOUT_S = 600.0
    ENDPOINT_PROBE_TIMEOUT_S = 15.0
    CONTEXT_SIZE = 2048
    BATCH_SIZE = 512
    VAD_THRESHOLD = 0.5


class WhisperServerDefaults:
    MODEL_REPO_ID = "ggerganov/whisper.cpp"
    MODEL_REPO_FALLBACK = "ggml-org/whisper-large-v3-turbo"
    MODEL_FILENAME = "ggml-large-v3-turbo.bin"
    VAD_REPO_ID = "ggml-org/whisper-vad"
    VAD_MODEL_NAME = "silero-v6.2.0"
    VAD_MODEL_FILENAME = "ggml-silero-v6.2.0.bin"
    # Pin verificato il 2026-08-20. Evita che install.sh cambi comportamento
    # da un giorno all'altro seguendo master di whisper.cpp.
    WHISPER_CPP_COMMIT = "339f2b4e27d7c3b52f44a124a854abba507acff3"
    SERVER_BINARY_NAME = "whisper-server"
    SYCL_LIBS = (
        "libggml-sycl.so",
        "libggml.so",
        "libggml-cpu.so",
        "libggml-base.so",
        "libwhisper.so",
    )


class UIConstraints:
    MIN_WINDOW_WIDTH = 1200
    MIN_WINDOW_HEIGHT = 800
    WINDOW_WIDTH = MIN_WINDOW_WIDTH
    WINDOW_HEIGHT = MIN_WINDOW_HEIGHT
    CARD_PADDING = 16
    CARD_MARGIN = 8
    CARD_BORDER_RADIUS = 6
    BUTTON_MIN_HEIGHT = 30
    STATUS_DOT_DIAMETER = 8
    SHORTCUT_BADGE_FONT_SIZE = 10
    MAX_GRID_COLUMNS = 2
    STATS_UPDATE_INTERVAL_MS = 1000
