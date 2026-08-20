"""Helper PulseAudio/PipeWire per il monitor source."""
from __future__ import annotations

import logging
import os
from typing import Optional

import sounddevice as sd

logger = logging.getLogger(__name__)
_UNSET = object()
_saved_pulse_source: object | str | None = _UNSET


def find_pulse_device() -> Optional[int]:
    try:
        for i, dev in enumerate(sd.query_devices()):
            if str(dev.get("name", "")).lower() == "pulse":
                return i
    except Exception as exc:
        logger.debug("Errore ricerca dispositivo pulse: %s", exc)
    try:
        for api in sd.query_hostapis():
            if "pulse" in str(api.get("name", "")).lower():
                idx = int(api.get("default_input_device", -1))
                if idx >= 0:
                    return idx
    except Exception as exc:
        logger.debug("Errore ricerca API pulse: %s", exc)
    return None


def resolve_monitor_device(device_name: str) -> tuple[object, Optional[str]]:
    if device_name and ".monitor" in device_name:
        pulse_idx = find_pulse_device()
        if pulse_idx is not None:
            return pulse_idx, device_name
        logger.warning("Dispositivo PulseAudio non trovato; provo il nome diretto")
    return device_name, None


def set_pulse_source(source_name: str) -> None:
    """Salva l'ambiente originale una sola volta, anche durante reconnect."""
    global _saved_pulse_source
    if _saved_pulse_source is _UNSET:
        _saved_pulse_source = os.environ.get("PULSE_SOURCE")
    os.environ["PULSE_SOURCE"] = source_name
    logger.info("PULSE_SOURCE impostato a %s", source_name)


def restore_pulse_source() -> None:
    global _saved_pulse_source
    if _saved_pulse_source is _UNSET:
        return
    if _saved_pulse_source is None:
        os.environ.pop("PULSE_SOURCE", None)
        logger.info("PULSE_SOURCE rimosso")
    else:
        os.environ["PULSE_SOURCE"] = str(_saved_pulse_source)
        logger.info("PULSE_SOURCE ripristinato a %s", _saved_pulse_source)
    _saved_pulse_source = _UNSET
