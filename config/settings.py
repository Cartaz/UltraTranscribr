"""Impostazioni persistenti e validate per UltraTranscribr."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional

from config.constants import AppMeta, ProcessDefaults, SYCLDefaults, UIConstraints

logger = logging.getLogger(__name__)


class ModelSize(str, Enum):
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
    def default(cls) -> "ModelSize":
        return cls.TURBO

    @classmethod
    def choices(cls) -> list[str]:
        return [m.value for m in cls]


class ComputeDevice(str, Enum):
    SYCL = "sycl"


class AudioSource(str, Enum):
    SYSTEM = "system"
    APPLICATION = "application"
    # Alias interno temporaneo: consente ai componenti non ancora rinominati
    # di interpretare il vecchio simbolo come la nuova sorgente di sistema.
    FIREFOX = "system"
    MICROPHONE = "microphone"

    @classmethod
    def choices(cls) -> list[str]:
        return [m.value for m in cls]


_LANG_RE = re.compile(r"^(?:auto|[a-z]{2,3}(?:-[a-z0-9]{2,8})?)$")


@dataclass(frozen=True)
class Settings:
    sample_rate: int = ProcessDefaults.SAMPLE_RATE
    channels: int = ProcessDefaults.CHANNELS
    chunk_ms: int = ProcessDefaults.CHUNK_MS
    dtype: str = ProcessDefaults.DTYPE

    model_size: str = ModelSize.TURBO.value
    device: str = ComputeDevice.SYCL.value
    compute_type: str = ProcessDefaults.COMPUTE_TYPE
    language: str = ProcessDefaults.LANGUAGE
    audio_source: str = AudioSource.SYSTEM.value
    beam_size: int = ProcessDefaults.BEAM_SIZE
    vad_filter: bool = ProcessDefaults.VAD_FILTER
    vad_min_silence_ms: int = ProcessDefaults.VAD_MIN_SILENCE_MS

    buffer_warn_threshold: int = ProcessDefaults.BUFFER_WARN_THRESHOLD
    history_retention_days: int = ProcessDefaults.HISTORY_RETENTION_DAYS
    sink_name: Optional[str] = None
    sink_search_keyword: str = ProcessDefaults.SINK_SEARCH_KEYWORD

    gpu_layers: int = SYCLDefaults.GPU_LAYERS
    server_port: int = SYCLDefaults.PORT

    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.sample_rate != ProcessDefaults.SAMPLE_RATE:
            errors.append("sample_rate deve essere 16000 Hz")
        if self.channels not in (1, 2):
            errors.append("channels deve essere 1 o 2")
        if not 100 <= self.chunk_ms <= 10000:
            errors.append("chunk_ms deve essere tra 100 e 10000")
        if self.dtype != "float32":
            errors.append("dtype supportato: float32")
        if self.model_size not in ModelSize.choices():
            errors.append(f"model_size non valido: {self.model_size}")
        if self.device != ComputeDevice.SYCL.value:
            errors.append("device deve essere sycl")
        if not _LANG_RE.match(str(self.language).lower()):
            errors.append(f"language non valida: {self.language}")
        if self.audio_source not in AudioSource.choices():
            errors.append(f"audio_source non valida: {self.audio_source}")
        if not 1 <= self.beam_size <= 64:
            errors.append("beam_size deve essere tra 1 e 64")
        if not 0 <= self.vad_min_silence_ms <= 10000:
            errors.append("vad_min_silence_ms fuori intervallo")
        if self.buffer_warn_threshold <= 0:
            errors.append("buffer_warn_threshold deve essere > 0")
        if not 0 <= self.history_retention_days <= 3650:
            errors.append("history_retention_days deve essere tra 0 e 3650")
        if not 1 <= self.server_port <= 65535:
            errors.append("server_port deve essere tra 1 e 65535")
        if self.window_width < UIConstraints.MIN_WINDOW_WIDTH:
            errors.append(
                f"window_width deve essere >= {UIConstraints.MIN_WINDOW_WIDTH}"
            )
        if self.window_height < UIConstraints.MIN_WINDOW_HEIGHT:
            errors.append(
                f"window_height deve essere >= {UIConstraints.MIN_WINDOW_HEIGHT}"
            )
        if errors:
            raise ValueError("; ".join(errors))

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_ms / 1000)

    @property
    def server_url(self) -> str:
        return f"http://{SYCLDefaults.HOST}:{self.server_port}"

    def with_(self, **overrides: object) -> "Settings":
        current = asdict(self)
        for key, value in overrides.items():
            if key not in current:
                raise AttributeError(f"Settings non ha il campo '{key}'")
            current[key] = value
        current["device"] = ComputeDevice.SYCL.value
        return Settings(**current)

    def save(self) -> None:
        """Salva atomicamente settings.json per evitare file troncati."""
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        fd, tmp_name = tempfile.mkstemp(
            prefix="settings.", suffix=".tmp", dir=AppMeta.CONFIG_DIR
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, AppMeta.SETTINGS_PATH)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        logger.info("Impostazioni salvate in %s", AppMeta.SETTINGS_PATH)

    @classmethod
    def load(cls) -> "Settings":
        if not AppMeta.SETTINGS_PATH.exists():
            return cls()
        try:
            with open(AppMeta.SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            valid_keys = set(cls.__dataclass_fields__)
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            filtered["device"] = ComputeDevice.SYCL.value

            # Migrazione non distruttiva dalla vecchia sorgente browser-specifica.
            # Il valore verrà scritto come "system" al successivo salvataggio.
            if filtered.get("audio_source") == "firefox":
                filtered["audio_source"] = AudioSource.SYSTEM.value
                logger.info("Sorgente audio migrata: firefox -> system")
            keyword = str(filtered.get("sink_search_keyword", "") or "")
            if keyword.casefold() == ProcessDefaults.LEGACY_FIREFOX_KEYWORD.casefold():
                filtered["sink_search_keyword"] = ProcessDefaults.SINK_SEARCH_KEYWORD
                logger.info("Keyword Firefox legacy rimossa dalla configurazione audio")

            old_width = filtered.get("window_width", UIConstraints.WINDOW_WIDTH)
            old_height = filtered.get("window_height", UIConstraints.WINDOW_HEIGHT)
            filtered["window_width"] = max(
                int(old_width), UIConstraints.MIN_WINDOW_WIDTH
            )
            filtered["window_height"] = max(
                int(old_height), UIConstraints.MIN_WINDOW_HEIGHT
            )
            if (
                filtered["window_width"] != old_width
                or filtered["window_height"] != old_height
            ):
                logger.info(
                    "Dimensioni finestra migrate al minimo supportato: %dx%d",
                    filtered["window_width"],
                    filtered["window_height"],
                )

            return cls(**filtered)
        except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            logger.warning("Impostazioni non valide (%s), uso i default", exc)
            return cls()