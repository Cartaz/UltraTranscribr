"""Helper PulseAudio/PipeWire per il monitor source."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

import sounddevice as sd

logger = logging.getLogger(__name__)
_UNSET = object()
_saved_pulse_source: object | str | None = _UNSET
_pulse_source_lock = threading.RLock()


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


@contextmanager
def temporary_pulse_source(source_name: str) -> Iterator[None]:
    """Temporarily select a Pulse source while a PortAudio stream is opened.

    ``PULSE_SOURCE`` is process-global, therefore concurrent session startup
    must serialize the tiny set/open/restore window. Once the stream is open,
    PulseAudio keeps that source connection and the environment can immediately
    be restored for the next session.
    """
    with _pulse_source_lock:
        original = os.environ.get("PULSE_SOURCE")
        os.environ["PULSE_SOURCE"] = source_name
        logger.info("PULSE_SOURCE temporaneo impostato a %s", source_name)
        try:
            yield
        finally:
            if original is None:
                os.environ.pop("PULSE_SOURCE", None)
            else:
                os.environ["PULSE_SOURCE"] = original
            logger.info("PULSE_SOURCE temporaneo ripristinato")


def set_pulse_source(source_name: str) -> None:
    """Legacy helper retained for callers/tests outside the multi-session path."""
    global _saved_pulse_source
    with _pulse_source_lock:
        if _saved_pulse_source is _UNSET:
            _saved_pulse_source = os.environ.get("PULSE_SOURCE")
        os.environ["PULSE_SOURCE"] = source_name
        logger.info("PULSE_SOURCE impostato a %s", source_name)


def restore_pulse_source() -> None:
    global _saved_pulse_source
    with _pulse_source_lock:
        if _saved_pulse_source is _UNSET:
            return
        if _saved_pulse_source is None:
            os.environ.pop("PULSE_SOURCE", None)
            logger.info("PULSE_SOURCE rimosso")
        else:
            os.environ["PULSE_SOURCE"] = str(_saved_pulse_source)
            logger.info("PULSE_SOURCE ripristinato a %s", _saved_pulse_source)
        _saved_pulse_source = _UNSET
