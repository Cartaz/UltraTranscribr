# core/pulse_helpers.py
"""Funzioni di utilita per la cattura audio tramite PulseAudio/PipeWire.

Gestisce la risoluzione del dispositivo 'pulse' e la manipolazione
della variabile d'ambiente PULSE_SOURCE per la cattura da monitor
source di PipeWire/PulseAudio.

Functions:
    find_pulse_device: Trova l'indice del dispositivo 'pulse'.
    resolve_monitor_device: Risolve il nome dispositivo per sounddevice.
    set_pulse_source: Imposta la variabile d'ambiente PULSE_SOURCE.
    restore_pulse_source: Ripristina la variabile PULSE_SOURCE originale.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import sounddevice as sd

logger = logging.getLogger(__name__)

# Chiave per salvare il valore originale di PULSE_SOURCE
_SAVED_PULSE_SOURCE_KEY: str = "_pulse_helpers_saved_source"


def find_pulse_device() -> Optional[int]:
    """Trova l'indice del dispositivo 'pulse' nella lista sounddevice.

    Cerca prima nella lista dispositivi, poi negli host API.

    Returns:
        Indice del dispositivo pulse, o None.
    """
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev.get("name", "") == "pulse":
                return i
    except Exception as exc:
        logger.debug("Errore ricerca dispositivo pulse: %s", exc)

    try:
        apis = sd.query_hostapis()
        for api in apis:
            if "pulse" in api.get("name", "").lower():
                default_in = api.get("default_input_device", -1)
                if default_in >= 0:
                    return default_in
    except Exception as exc:
        logger.debug("Errore ricerca API pulse: %s", exc)

    return None


def resolve_monitor_device(device_name: str) -> tuple:
    """Risolve il nome del dispositivo per sounddevice.

    Se il nome contiene ".monitor", cerca il dispositivo PulseAudio
    e restituisce la tupla (indice_pulse, nome_monitor_source).
    Altrimenti restituisce (nome, None).

    Args:
        device_name: Nome del dispositivo audio.

    Returns:
        Tupla (dispositivo_per_sounddevice, nome_pulse_source_o_None).
    """
    if device_name and ".monitor" in device_name:
        pulse_idx = find_pulse_device()
        if pulse_idx is not None:
            logger.info("Uso dispositivo PulseAudio (index=%d) con PULSE_SOURCE=%s",
                        pulse_idx, device_name)
            return pulse_idx, device_name
        logger.warning("Dispositivo PulseAudio non trovato. Provo nome diretto.")
    return device_name, None


def set_pulse_source(source_name: str) -> None:
    """Imposta PULSE_SOURCE env var e salva il valore originale.

    Il valore originale viene salvato come attributo del modulo
    per consentire il ripristino successivo.

    Args:
        source_name: Nome del source PulseAudio da usare.
    """
    globals()[_SAVED_PULSE_SOURCE_KEY] = os.environ.get("PULSE_SOURCE")
    os.environ["PULSE_SOURCE"] = source_name
    logger.info("PULSE_SOURCE impostato a %s", source_name)


def restore_pulse_source() -> None:
    """Ripristina la variabile d'ambiente PULSE_SOURCE originale."""
    saved = globals().get(_SAVED_PULSE_SOURCE_KEY)
    if saved is not None:
        os.environ["PULSE_SOURCE"] = saved
        logger.info("PULSE_SOURCE ripristinato a %s", saved)
        globals()[_SAVED_PULSE_SOURCE_KEY] = None
    elif "PULSE_SOURCE" in os.environ:
        del os.environ["PULSE_SOURCE"]
        logger.info("PULSE_SOURCE rimosso")
