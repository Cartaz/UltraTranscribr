"""Public configuration exports for UltraTranscribr.

The config layer contains application metadata, process/UI constants and the
persistent Settings model. Presentation styling lives exclusively in ui/web/.
"""

from config.constants import (
    AppMeta,
    DictationDefaults,
    ProcessDefaults,
    SYCLDefaults,
    UIConstraints,
    WhisperServerDefaults,
)
from config.settings import (
    AudioSource,
    ComputeDevice,
    DictationActivationMode,
    DictationInsertionMode,
    ModelSize,
    Settings,
)

__all__ = [
    "AppMeta",
    "DictationDefaults",
    "ProcessDefaults",
    "UIConstraints",
    "SYCLDefaults",
    "WhisperServerDefaults",
    "Settings",
    "ModelSize",
    "ComputeDevice",
    "AudioSource",
    "DictationActivationMode",
    "DictationInsertionMode",
]
