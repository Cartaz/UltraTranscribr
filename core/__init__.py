# core/__init__.py
"""Pacchetto core — logica di business dell'applicazione UltraTranscribr (SYCL).

Il livello core non importa mai da ui/. La comunicazione con l'UI
avviene esclusivamente tramite l'event bus.

Exports:
    AppController: Controller principale dell'applicazione.
    EventBus: Bus eventi singleton per comunicazione moduli.
    WhisperBackend: Gestore del server whisper.cpp con SYCL.
    WhisperModelManager: Gestore download e cache modelli GGUF.
    FileTranscriberThread: Thread per trascrizione file audio.
    TranscriberThread: Thread per trascrizione live.
    ProcessState: Modello stato processo.
    StatusEnum: Enum stati processo.
"""

from core.app_controller import AppController
from core.event_bus import EventBus
from core.exceptions import (
    AppError,
    AudioCaptureError,
    ConfigError,
    GPUNotAvailableError,
    SinkNotFoundError,
    TranscriptionError,
)
from core.file_transcriber import FileTranscriberThread
from core.models import ProcessState, StatusEnum
from core.transcriber import TranscriberThread
from core.whisper_backend import WhisperBackend
from core.whisper_models import WhisperModelManager

__all__ = [
    "AppController",
    "EventBus",
    "WhisperBackend",
    "WhisperModelManager",
    "FileTranscriberThread",
    "TranscriberThread",
    "AppError",
    "AudioCaptureError",
    "ConfigError",
    "GPUNotAvailableError",
    "SinkNotFoundError",
    "TranscriptionError",
    "ProcessState",
    "StatusEnum",
]
