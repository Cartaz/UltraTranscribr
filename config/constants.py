# config/constants.py
"""Costanti globali dell'applicazione UltraTranscribr con accelerazione SYCL.

Le costanti sono raggruppate in classi per dominio. I percorsi sono
calcolati dinamicamente con pathlib.Path e variabili d'ambiente XDG.

Classes:
    AppMeta: Metadati dell'applicazione.
    ProcessDefaults: Valori predefiniti per i processi.
    UIConstraints: Vincoli e dimensioni dell'interfaccia.
    SYCLDefaults: Parametri predefiniti per il backend SYCL/GPU.
    WhisperServerDefaults: Parametri del server whisper.cpp.
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg_config_home() -> Path:
    """Restituisce il percorso XDG_CONFIG_HOME conforme alla specifica.

    Returns:
        Percorso della directory di configurazione utente.
    """
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_cache_home() -> Path:
    """Restituisce il percorso XDG_CACHE_HOME conforme alla specifica.

    Returns:
        Percorso della directory di cache utente.
    """
    return Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))


class AppMeta:
    """Metadati identificativi dell'applicazione UltraTranscribr."""

    NAME: str = "UltraTranscribr"
    VERSION: str = "5.2.0"
    ID: str = "com.ultratranscribr.app"
    DESCRIPTION: str = "Trascrizione audio accelerata GPU Intel Arc (SYCL)"
    LICENSE: str = "MIT"
    CONFIG_DIR: Path = _xdg_config_home() / "ultratranscribr"
    SETTINGS_PATH: Path = _xdg_config_home() / "ultratranscribr" / "settings.json"
    LOG_PATH: Path = _xdg_config_home() / "ultratranscribr" / "ultratranscribr.log"
    DESKTOP_DIR: Path = Path.home() / ".local" / "share" / "applications"
    CACHE_DIR: Path = _xdg_cache_home() / "ultratranscribr"
    MODELS_DIR: Path = _xdg_cache_home() / "ultratranscribr" / "models" / "gguf"


class ProcessDefaults:
    """Valori predefiniti per i processi audio e trascrizione."""

    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1
    CHUNK_MS: int = 3000
    DTYPE: str = "float32"
    MODEL_SIZE: str = "large-v3-turbo"
    DEVICE: str = "sycl"
    COMPUTE_TYPE: str = "f16"
    LANGUAGE: str = "en"
    AUDIO_SOURCE: str = "firefox"
    BEAM_SIZE: int = 5
    VAD_FILTER: bool = True
    VAD_MIN_SILENCE_MS: int = 500
    BUFFER_WARN_THRESHOLD: int = 20
    SINK_SEARCH_KEYWORD_FIREFOX: str = "Firefox"
    SINK_SEARCH_KEYWORD_MIC: str = "HDA Intel PCH"
    RECONNECT_DELAY: float = 2.0
    MAX_RECONNECT_ATTEMPTS: int = 5
    OVERLAP_DURATION_S: float = 2.0
    SEGMENT_LENGTH_S: float = 10.0
    MIN_SEGMENT_S: float = 2.0
    # Soglia RMS per il rilevamento del silenzio lato client.
    # Audio con RMS sotto questa soglia viene saltato per evitare
    # allucinazioni del modello Whisper ("grazie a tutti", ecc.).
    # Valore abbassato da 0.01 a 0.005 per non scartare speech quieto.
    # Whisper e bravo a trascrivere audio quieto e le allucinazioni
    # sono filtrate da strip_hallucinations in text_dedup.py.
    # alltranscribr non ha silence detection e non perde contenuto.
    SILENCE_RMS_THRESHOLD: float = 0.005


class SYCLDefaults:
    """Parametri predefiniti per il backend SYCL su GPU Intel Arc."""

    ONEAPI_DEVICE_SELECTOR: str = "level_zero:0"
    GPU_LAYERS: int = 99
    PORT: int = 8082
    HOST: str = "127.0.0.1"
    HEALTH_TIMEOUT_S: float = 90.0
    HEALTH_POLL_INTERVAL_S: float = 0.5
    # 5 minuti: sufficiente per trascrivere un segmento di 10s anche su
    # GPU lenta, senza bloccare indefinitamente il thread se il server
    # smette di rispondere. Il valore precedente (300000s = 83 ore)
    # era un bug.
    REQUEST_TIMEOUT_S: float = 300000.0
    CONTEXT_SIZE: int = 2048
    BATCH_SIZE: int = 512
    # Soglia VAD Silero per il flag --vad di whisper-server.
    # Valori tipici: 0.4-0.6. Valori piu alti = meno sensibile.
    VAD_THRESHOLD: float = 0.5


class WhisperServerDefaults:
    """Parametri di default per il server whisper.cpp."""

    # Modello GGUF Whisper Large V3 Turbo su HuggingFace
    MODEL_REPO_ID: str = "ggml-org/whisper-large-v3-turbo"
    MODEL_FILENAME: str = "ggml-large-v3-turbo.bin"
    # Percorso binary nel venv (immune da pacman)
    SERVER_BINARY_NAME: str = "whisper-server"
    # Librerie condivise SYCL richieste in .venv/lib/
    SYCL_LIBS: tuple[str, ...] = (
        "libggml-sycl.so",
        "libggml.so",
        "libggml-cpu.so",
        "libggml-base.so",
        "libwhisper.so",
    )


class UIConstraints:
    """Vincoli e dimensioni dell'interfaccia utente."""

    WINDOW_WIDTH: int = 480
    WINDOW_HEIGHT: int = 540
    CARD_PADDING: int = 16
    CARD_MARGIN: int = 8
    CARD_BORDER_RADIUS: int = 6
    BUTTON_MIN_HEIGHT: int = 30
    STATUS_DOT_DIAMETER: int = 8
    SHORTCUT_BADGE_FONT_SIZE: int = 10
    MAX_GRID_COLUMNS: int = 2
    STATS_UPDATE_INTERVAL_MS: int = 1000
