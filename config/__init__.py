# config/__init__.py
"""Pacchetto configurazione dell'applicazione UltraTranscribr (SYCL).

Esporre solo le classi pubbliche necessarie. Il livello config
non importa mai da core/ o ui/.

Exports:
    AppMeta: Metadati dell'applicazione.
    ProcessDefaults: Valori predefiniti per i processi.
    UIConstraints: Vincoli e dimensioni dell'interfaccia.
    SYCLDefaults: Parametri predefiniti per il backend SYCL.
    WhisperServerDefaults: Parametri del server whisper.cpp.
    Settings: Impostazioni persistenti dell'applicazione.
    ModelSize: Enum dimensioni modello Whisper.
    ComputeDevice: Enum backend di calcolo.
    AudioSource: Enum sorgente audio.
    ThemeColors: Token di colore Breeze Dark.
"""

from config.constants import (
    AppMeta,
    ProcessDefaults,
    SYCLDefaults,
    UIConstraints,
    WhisperServerDefaults,
)
from config.settings import AudioSource, ComputeDevice, ModelSize, Settings
from config.theme import ThemeColors

__all__ = [
    "AppMeta",
    "ProcessDefaults",
    "UIConstraints",
    "SYCLDefaults",
    "WhisperServerDefaults",
    "Settings",
    "ModelSize",
    "ComputeDevice",
    "AudioSource",
    "ThemeColors",
]
