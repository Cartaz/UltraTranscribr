# config/settings.py
"""Impostazioni utente persistenti per UltraTranscribr con accelerazione SYCL.

Gestisce tutte le impostazioni dell'applicazione tramite dataclass
congelata. La persistenza avviene in JSON nella directory XDG
appropriata, conforme alla XDG Base Directory Specification.

Solo GPU Intel Arc tramite SYCL e supportata. Nessun fallback CPU,
nessun supporto NPU o CUDA.

Classes:
    ModelSize: Enum delle dimensioni del modello Whisper GGUF.
    ComputeDevice: Enum del backend di calcolo (solo SYCL).
    AudioSource: Enum delle sorgenti audio (Firefox / Microfono).
    Settings: Impostazioni immutabili dell'applicazione.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from config.constants import AppMeta, ProcessDefaults, SYCLDefaults, UIConstraints

logger = logging.getLogger(__name__)


class ModelSize(str, Enum):
    """Dimensioni del modello Whisper GGUF per whisper.cpp.

    Solo i modelli disponibili in formato GGUF per whisper.cpp sono
    elencati. Il formato CTranslate2 non e piu supportato.
    """

    TINY = "tiny"
    TINY_EN = "tiny.en"
    BASE = "base"
    BASE_EN = "base.en"
    SMALL = "small"
    SMALL_EN = "small.en"
    MEDIUM = "medium"
    MEDIUM_EN = "medium.en"
    LARGE_V3 = "large-v3"
    TURBO = "large-v3-turbo"

    @classmethod
    def default(cls) -> ModelSize:
        """Restituisce il modello predefinito.

        Returns:
            Il modello TURBO (large-v3-turbo) come scelta ottimale
            per il miglior rapporto precisione/velocita su iGPU Arc.
        """
        return cls.TURBO

    @classmethod
    def choices(cls) -> list[str]:
        """Restituisce tutti i valori disponibili.

        Returns:
            Lista dei nomi dei modelli.
        """
        return [m.value for m in cls]


class ComputeDevice(str, Enum):
    """Backend di calcolo — solo SYCL su GPU Intel Arc.

    Nessun fallback CPU, nessun supporto NPU o CUDA.
    L'unico valore valido e SYCL, che utilizza il backend Level Zero
    per l'offload completo dei tensori sulla GPU Intel Arc integrata.
    """

    SYCL = "sycl"


class AudioSource(str, Enum):
    """Sorgente audio per la cattura."""

    FIREFOX = "firefox"
    MICROPHONE = "microphone"

    @classmethod
    def choices(cls) -> list[str]:
        """Restituisce tutti i valori disponibili.

        Returns:
            Lista degli identificativi delle sorgenti.
        """
        return [m.value for m in cls]


@dataclass(frozen=True)
class Settings:
    """Impostazioni immutabili dell'applicazione con accelerazione SYCL.

    Crea una copia modificata con:
        new_settings = settings.with_(model_size=ModelSize.LARGE_V3)

    Attributes:
        sample_rate: Frequenza di campionamento in Hz.
        channels: Numero di canali audio.
        chunk_ms: Millisecondi per blocco audio.
        dtype: Tipo dati numpy per l'audio PCM.
        model_size: Identificativo del modello Whisper GGUF.
        device: Backend di calcolo (sempre "sycl").
        compute_type: Formato modello GGUF (es. "f16").
        language: Lingua di trascrizione (ISO 639-1).
        audio_source: Sorgente audio ("firefox" o "microphone").
        beam_size: Larghezza della beam search.
        vad_filter: Attiva il rilevamento attivita vocale.
        vad_min_silence_ms: Silenzio minimo per dividere i segmenti.
        buffer_warn_threshold: Blocchi in coda prima dello stato BUFFERING.
        sink_name: Nome sink specifico, None per auto-detect.
        sink_search_keyword: Parola chiave per filtrare la lista sink.
        gpu_layers: Numero di layer da offloadare sulla GPU (99 = tutti).
        server_port: Porta del server whisper.cpp.
        window_width: Larghezza iniziale finestra.
        window_height: Altezza iniziale finestra.
    """

    # ── Audio ──────────────────────────────────────────────────────
    sample_rate: int = ProcessDefaults.SAMPLE_RATE
    channels: int = ProcessDefaults.CHANNELS
    chunk_ms: int = ProcessDefaults.CHUNK_MS
    dtype: str = ProcessDefaults.DTYPE

    # ── Trascrizione ──────────────────────────────────────────────
    model_size: str = ModelSize.TURBO.value
    device: str = ComputeDevice.SYCL.value
    compute_type: str = ProcessDefaults.COMPUTE_TYPE
    language: str = ProcessDefaults.LANGUAGE
    audio_source: str = AudioSource.FIREFOX.value
    beam_size: int = ProcessDefaults.BEAM_SIZE
    vad_filter: bool = ProcessDefaults.VAD_FILTER
    vad_min_silence_ms: int = ProcessDefaults.VAD_MIN_SILENCE_MS

    # ── Buffer ────────────────────────────────────────────────────
    buffer_warn_threshold: int = ProcessDefaults.BUFFER_WARN_THRESHOLD

    # ── Sink ──────────────────────────────────────────────────────
    sink_name: Optional[str] = None
    sink_search_keyword: str = ProcessDefaults.SINK_SEARCH_KEYWORD_FIREFOX

    # ── SYCL / GPU ────────────────────────────────────────────────
    gpu_layers: int = SYCLDefaults.GPU_LAYERS
    server_port: int = SYCLDefaults.PORT

    # ── UI ────────────────────────────────────────────────────────
    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    # ── Proprieta derivata ────────────────────────────────────────
    @property
    def chunk_samples(self) -> int:
        """Numero di campioni audio per blocco.

        Returns:
            Il numero di campioni calcolato da sample_rate e chunk_ms.
        """
        return int(self.sample_rate * self.chunk_ms / 1000)

    @property
    def server_url(self) -> str:
        """URL base del server whisper.cpp.

        Returns:
            URL del server nel formato http://host:port.
        """
        return f"http://{SYCLDefaults.HOST}:{self.server_port}"

    # ── Copia con override ────────────────────────────────────────
    def with_(self, **overrides: object) -> Settings:
        """Restituisce una nuova Settings con i campi indicati sostituiti.

        Args:
            **overrides: Campi da sostituire e loro nuovi valori.

        Returns:
            Una nuova istanza di Settings con gli override applicati.

        Raises:
            AttributeError: Se un campo non esiste nella dataclass.
        """
        current = asdict(self)
        for key, value in overrides.items():
            if key not in current:
                raise AttributeError(f"Settings non ha il campo '{key}'")
            current[key] = value
        return Settings(**current)

    # ── Persistenza ───────────────────────────────────────────────
    def save(self) -> None:
        """Serializza le impostazioni in JSON su disco.

        Salva nella directory XDG_CONFIG_HOME/ultratranscribr/settings.json.
        """
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        with open(AppMeta.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Impostazioni salvate in %s", AppMeta.SETTINGS_PATH)

    @classmethod
    def load(cls) -> Settings:
        """Carica le impostazioni da disco, con fallback ai default.

        Returns:
            Istanza di Settings con valori da disco o predefiniti.
        """
        if not AppMeta.SETTINGS_PATH.exists():
            logger.info("Nessun file impostazioni trovato, uso i default")
            return cls()

        try:
            with open(AppMeta.SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in valid_keys}

            # Forza sempre device=sycl (nessun fallback CPU)
            filtered["device"] = ComputeDevice.SYCL.value

            settings = cls(**filtered)
            logger.info("Impostazioni caricate — model=%s, device=%s",
                        settings.model_size, settings.device)
            return settings
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Impossibile caricare le impostazioni (%s), uso i default", exc)
            return cls()
