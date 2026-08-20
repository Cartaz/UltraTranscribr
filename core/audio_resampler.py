# core/audio_resampler.py
"""Utilita di resampling audio per la cattura da microfono.

Fornisce funzioni per il resampling da sample rate nativo del
dispositivo hardware al sample rate target di faster-whisper (16 kHz).

Functions:
    resample: Resampla un array audio tramite interpolazione lineare.
    query_device_sample_rate: Interroga il sample rate nativo di un dispositivo.
"""

from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# Sample rate target per faster-whisper (fisso, non modificabile)
WHISPER_SAMPLE_RATE: int = 16000


def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resampla audio da orig_sr a target_sr tramite interpolazione lineare.

    Usa np.interp per interpolazione lineare: sufficiente per segnali
    vocali a 16 kHz. Non richiede dipendenze aggiuntive oltre a numpy.

    Args:
        audio: Array numpy float32 mono.
        orig_sr: Sample rate originale.
        target_sr: Sample rate target.

    Returns:
        Array numpy float32 resamplato a target_sr.
    """
    if orig_sr == target_sr:
        return audio
    duration = audio.shape[0] / orig_sr
    target_length = int(duration * target_sr)
    if target_length <= 0:
        return np.array([], dtype=np.float32)
    orig_indices = np.arange(audio.shape[0], dtype=np.float64)
    target_indices = np.linspace(0, audio.shape[0] - 1, target_length)
    resampled = np.interp(target_indices, orig_indices, audio)
    return resampled.astype(np.float32)


def query_device_sample_rate(device: object) -> int:
    """Interroga il sample rate nativo del dispositivo.

    Se il dispositivo supporta 16000 Hz, lo usa direttamente.
    Altrimenti usa il default_samplerate riportato da sounddevice.

    Args:
        device: Nome o indice del dispositivo sounddevice.

    Returns:
        Sample rate nativo da usare per aprire lo stream.
    """
    try:
        dev_info = sd.query_devices(device)
        default_sr = int(dev_info.get("default_samplerate", 48000))
        logger.info("Dispositivo '%s' — sample rate nativo: %d Hz",
                    dev_info.get("name", "?"), default_sr)
    except Exception as exc:
        logger.warning("Impossibile interrogare il sample rate del dispositivo: %s", exc)
        default_sr = 48000

    if default_sr == WHISPER_SAMPLE_RATE:
        return WHISPER_SAMPLE_RATE

    logger.info("Il dispositivo non supporta 16 kHz nativamente, "
                 "uso %d Hz con resampling a %d Hz",
                 default_sr, WHISPER_SAMPLE_RATE)
    return default_sr
