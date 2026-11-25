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
        return cls(ProcessDefaults.MODEL_SIZE)

    @classmethod
    def choices(cls) -> list[str]:
        return [
            cls.LARGE_V3.value,
            cls.TURBO.value,
            cls.MEDIUM.value,
        ]


class ComputeDevice(str, Enum):
    SYCL = "sycl"


class AudioSource(str, Enum):
    SYSTEM = "system"
    APPLICATION = "application"
    FIREFOX = "system"
    MICROPHONE = "microphone"

    @classmethod
    def choices(cls) -> list[str]:
        return [m.value for m in cls]


class DictationActivationMode(str, Enum):
    PUSH_TO_TALK = "push_to_talk"
    TOGGLE = "toggle"

    @classmethod
    def choices(cls) -> list[str]:
        return [item.value for item in cls]


class DictationInsertionMode(str, Enum):
    LIVE = "live"
    FINAL = "final"

    @classmethod
    def choices(cls) -> list[str]:
        return [item.value for item in cls]


_LANG_RE = re.compile(r"^(?:auto|[a-z]{2,3}(?:-[a-z0-9]{2,8})?)$")


INTEGER_FIELDS = {
    "sample_rate",
    "channels",
    "chunk_ms",
    "beam_size",
    "vad_min_silence_ms",
    "buffer_warn_threshold",
    "history_retention_days",
    "meeting_audio_retention_days",
    "gpu_layers",
    "server_port",
    "backend_instances",
    "window_width",
    "window_height",
}
BOOLEAN_FIELDS = {"vad_filter", "live_microphone_recording", "preload_model"}
SUPPORTED_LANGUAGES = frozenset(
    "en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue auto".split()
)


def normalize_language(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Lingua non valida: usa it, en oppure auto")
    normalized = value.strip().lower()
    if (
        not _LANG_RE.fullmatch(normalized)
        or normalized.split("-")[0] not in SUPPORTED_LANGUAGES
    ):
        raise ValueError(
            "Lingua non valida: usa it, en oppure auto (o un codice supportato)"
        )
    return normalized.split("-")[0]


@dataclass(frozen=True)
class Settings:
    sample_rate: int = ProcessDefaults.SAMPLE_RATE
    channels: int = ProcessDefaults.CHANNELS
    chunk_ms: int = ProcessDefaults.CHUNK_MS
    dtype: str = ProcessDefaults.DTYPE

    model_size: str = ProcessDefaults.MODEL_SIZE
    device: str = ComputeDevice.SYCL.value
    compute_type: str = ProcessDefaults.COMPUTE_TYPE
    language: str = ProcessDefaults.LANGUAGE
    audio_source: str = AudioSource.SYSTEM.value
    beam_size: int = ProcessDefaults.BEAM_SIZE
    vad_filter: bool = ProcessDefaults.VAD_FILTER
    vad_min_silence_ms: int = ProcessDefaults.VAD_MIN_SILENCE_MS

    buffer_warn_threshold: int = ProcessDefaults.BUFFER_WARN_THRESHOLD
    history_retention_days: int = ProcessDefaults.HISTORY_RETENTION_DAYS
    meeting_audio_retention_days: int = ProcessDefaults.MEETING_AUDIO_RETENTION_DAYS
    live_microphone_recording: bool = False
    sink_name: Optional[str] = None
    sink_search_keyword: str = ProcessDefaults.SINK_SEARCH_KEYWORD

    gpu_layers: int = SYCLDefaults.GPU_LAYERS
    server_port: int = SYCLDefaults.PORT
    backend_instances: int = 1
    preload_model: bool = False

    dictation_activation_mode: str = DictationActivationMode.PUSH_TO_TALK.value
    dictation_insertion_mode: str = DictationInsertionMode.LIVE.value
    window_x: Optional[int] = None
    window_y: Optional[int] = None
    window_width: int = UIConstraints.WINDOW_WIDTH
    window_height: int = UIConstraints.WINDOW_HEIGHT

    def __post_init__(self) -> None:
        for key in INTEGER_FIELDS:
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} deve essere un intero")
        for key in BOOLEAN_FIELDS:
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} deve essere vero o falso")
        object.__setattr__(self, "language", normalize_language(self.language))
        for key in ("sink_name", "sink_search_keyword"):
            value = getattr(self, key)
            if key == "sink_name" and value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{key} deve essere testo")
            object.__setattr__(
                self, key, value.strip() or (None if key == "sink_name" else "")
            )
        errors: list[str] = []
        fixed = {
            "sample_rate": ProcessDefaults.SAMPLE_RATE,
            "device": "sycl",
            "dtype": "float32",
            "gpu_layers": SYCLDefaults.GPU_LAYERS,
            "compute_type": ProcessDefaults.COMPUTE_TYPE,
        }
        for key, expected in fixed.items():
            if getattr(self, key) != expected:
                errors.append(f"{key} fisso per il motore disponibile: {expected}")
        limits = {
            "channels": (1, 2),
            "chunk_ms": (100, 10000),
            "beam_size": (1, 64),
            "vad_min_silence_ms": (0, 10000),
            "buffer_warn_threshold": (1, None),
            "history_retention_days": (0, 3650),
            "meeting_audio_retention_days": (0, 3650),
            "server_port": (1, 65535),
            "backend_instances": (1, 4),
            "window_width": (UIConstraints.MIN_WINDOW_WIDTH, None),
            "window_height": (UIConstraints.MIN_WINDOW_HEIGHT, None),
        }
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if value < low or high is not None and value > high:
                errors.append(
                    f"{key} fuori intervallo ({low}–{high if high is not None else 'massimo libero'})"
                )
        choices = {
            "model_size": ModelSize.choices(),
            "audio_source": AudioSource.choices(),
            "dictation_activation_mode": DictationActivationMode.choices(),
            "dictation_insertion_mode": DictationInsertionMode.choices(),
        }
        for key, allowed in choices.items():
            if getattr(self, key) not in allowed:
                errors.append(f"{key} non valido: {getattr(self, key)}")
        if self.server_port + self.backend_instances - 1 > 65535:
            errors.append("le porte delle istanze backend superano 65535")
        for key in ("window_x", "window_y"):
            value = getattr(self, key)
            if value is not None and type(value) is not int:
                errors.append(f"{key} deve essere un intero o null")
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
        return Settings(**current)

    def save(self) -> None:
        AppMeta.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        fd, tmp_name = tempfile.mkstemp(
            prefix="settings.", suffix=".tmp", dir=AppMeta.CONFIG_DIR
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
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
            if not isinstance(data, dict):
                raise ValueError("Il file delle impostazioni non contiene un oggetto")
            valid_keys = set(cls.__dataclass_fields__)
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            filtered["device"] = ComputeDevice.SYCL.value

            if filtered.get("audio_source") == "firefox":
                filtered["audio_source"] = AudioSource.SYSTEM.value
                logger.info("Sorgente audio migrata: firefox -> system")
            keyword = str(filtered.get("sink_search_keyword", "") or "")
            if keyword.casefold() == ProcessDefaults.LEGACY_FIREFOX_KEYWORD.casefold():
                filtered["sink_search_keyword"] = ProcessDefaults.SINK_SEARCH_KEYWORD
                logger.info("Keyword Firefox legacy rimossa dalla configurazione audio")

            selected_model = str(
                filtered.get("model_size", ProcessDefaults.MODEL_SIZE) or ""
            )
            if selected_model != ModelSize.LARGE_V3.value:
                filtered["model_size"] = ProcessDefaults.MODEL_SIZE
                logger.info(
                    "Modello legacy/non gestito '%s': migrazione a %s",
                    selected_model,
                    ProcessDefaults.MODEL_SIZE,
                )

            for coordinate_name in ("window_x", "window_y"):
                coordinate = filtered.get(coordinate_name)
                if coordinate is None:
                    continue
                try:
                    if isinstance(coordinate, bool):
                        raise ValueError
                    parsed = int(coordinate)
                    if float(coordinate) != parsed:
                        raise ValueError
                    filtered[coordinate_name] = parsed
                except (TypeError, ValueError, OverflowError):
                    filtered[coordinate_name] = None
                    logger.info(
                        "Coordinata finestra %s non valida: ripristino automatico",
                        coordinate_name,
                    )

            old_width = filtered.get("window_width", UIConstraints.WINDOW_WIDTH)
            old_height = filtered.get("window_height", UIConstraints.WINDOW_HEIGHT)
            for key, value, minimum in (
                ("window_width", old_width, UIConstraints.MIN_WINDOW_WIDTH),
                ("window_height", old_height, UIConstraints.MIN_WINDOW_HEIGHT),
            ):
                try:
                    parsed = int(value)
                    if isinstance(value, bool) or float(value) != parsed:
                        raise ValueError
                    filtered[key] = max(parsed, minimum)
                except (ValueError, TypeError, OverflowError):
                    filtered[key] = getattr(cls(), key)
            if (
                filtered["window_width"] != old_width
                or filtered["window_height"] != old_height
            ):
                logger.info(
                    "Dimensioni finestra migrate al minimo supportato: %dx%d",
                    filtered["window_width"],
                    filtered["window_height"],
                )

            try:
                return cls(**filtered)
            except (TypeError, ValueError):
                # Repair bad fields independently: a corrupt numeric preference
                # must not reset the user's language or other valid choices.
                defaults = cls()
                repaired = {}
                for key, value in filtered.items():
                    try:
                        repaired[key] = getattr(cls(**{key: value}), key)
                    except (TypeError, ValueError):
                        repaired[key] = getattr(defaults, key)
                        logger.warning(
                            "Impostazione %s non valida: ripristinato solo questo campo",
                            key,
                        )
                if (
                    repaired.get("server_port", defaults.server_port)
                    + repaired.get("backend_instances", 1)
                    - 1
                    > 65535
                ):
                    repaired["backend_instances"] = 1
                return cls(**repaired)
        except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
            logger.warning("Impostazioni non valide (%s), uso i default", exc)
            return cls()
