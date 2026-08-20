# core/sink_finder.py
"""Discovery unificato dei dispositivi audio PipeWire / PulseAudio.

Scopre sia i monitor source per Firefox sia i microfoni per la cattura
audio. Le due strategie di ricerca sono mantenute separate e selezionate
tramite il parametro audio_source.

Functions:
    find_source: Trova il dispositivo audio in base alla fonte.
    find_firefox_sink: Trova il monitor source per Firefox.
    find_microphone: Trova il dispositivo microfono.
    list_available_devices: Elenca tutti i dispositivi di input.
    list_all_monitor_sources: Elenca solo le sorgenti monitor.
    debug_dump: Dump info debug dispositivi audio.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

import sounddevice as sd

from config.settings import AudioSource, Settings
from core.sink_helpers import (
    extract_sink_index,
    get_sink_name,
    hostapi_name,
)

logger = logging.getLogger(__name__)


def find_source(
    settings: Settings | None = None,
    audio_source: Optional[str] = None,
) -> Optional[str]:
    """Trova il dispositivo audio in base alla fonte selezionata.

    Args:
        settings: Impostazioni dell'app (usa keyword per la ricerca).
        audio_source: Sorgente audio ("firefox" o "microphone").

    Returns:
        Nome del dispositivo che sounddevice puo usare, o None.
    """
    if settings is None:
        settings = Settings()
    source = audio_source or settings.audio_source

    if source == AudioSource.FIREFOX.value:
        return find_firefox_sink(settings)
    return find_microphone(settings)


def find_firefox_sink(settings: Settings | None = None) -> Optional[str]:
    """Trova il monitor source per l'audio di Firefox.

    Prova tutti i metodi in ordine di affidabilita.

    Args:
        settings: Impostazioni dell'app (usa keyword per la ricerca).

    Returns:
        Nome del dispositivo che sounddevice puo usare, o None.
    """
    if settings is None:
        settings = Settings()
    keyword = settings.sink_search_keyword

    result = _find_monitor_via_sounddevice(keyword)
    if result:
        logger.info("Sink trovato via sounddevice: %s", result)
        return result

    result = _find_via_pactl(keyword)
    if result:
        logger.info("Sink trovato via pactl: %s", result)
        return result

    logger.warning("Impossibile trovare il sink di Firefox con nessun metodo")
    return None


def find_microphone(settings: Settings | None = None) -> Optional[str]:
    """Trova il dispositivo microfono per la cattura audio.

    Args:
        settings: Impostazioni dell'app (usa keyword per la ricerca).

    Returns:
        Nome del dispositivo che sounddevice puo usare, o None.
    """
    if settings is None:
        settings = Settings()
    keyword = settings.sink_search_keyword

    result = _find_mic_via_sounddevice(keyword)
    if result:
        logger.info("Microfono trovato via sounddevice: %s", result)
        return result

    logger.warning("Impossibile trovare il microfono con nessun metodo")
    return None


def list_available_devices() -> list[dict]:
    """Elenca tutti i dispositivi di input audio disponibili.

    Ogni dispositivo include flag is_monitor e is_mic per consentire
    il filtraggio lato UI in base alla fonte selezionata.

    Returns:
        Lista di dict con 'name', 'description', 'id', 'is_monitor', 'is_mic'.
    """
    devices = []
    try:
        device_list = sd.query_devices()
    except Exception as exc:
        logger.error("Impossibile interrogare i dispositivi: %s", exc)
        return []

    for i, dev in enumerate(device_list):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        hostapi = dev.get("hostapi", 0)
        is_monitor = ".monitor" in name or "monitor" in name.lower()
        devices.append({
            "id": i,
            "name": name,
            "description": name,
            "is_monitor": is_monitor,
            "is_mic": not is_monitor,
            "channels": dev.get("max_input_channels", 0),
            "samplerate": dev.get("default_samplerate", 0),
            "hostapi_name": hostapi_name(hostapi),
        })

    return devices


def list_all_monitor_sources() -> list[dict]:
    """Restituisce solo le sorgenti monitor (sink monitors).

    Returns:
        Lista di dict delle sole sorgenti monitor.
    """
    all_devs = list_available_devices()
    return [d for d in all_devs if d["is_monitor"]]


def _find_monitor_via_sounddevice(keyword: str) -> Optional[str]:
    """Cerca un monitor source tramite la lista dispositivi sounddevice.

    Args:
        keyword: Parola chiave da cercare nel nome del dispositivo.

    Returns:
        Nome del dispositivo trovato, o None.
    """
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Errore query sounddevice: %s", exc)
        return None

    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        if keyword.lower() in name.lower():
            return name

    default_output = sd.default.device[1]
    if (default_output is not None and default_output >= 0
            and default_output < len(devices)):
        default_name = devices[default_output].get("name", "")
        monitor_name = default_name + ".monitor"
        for dev in devices:
            if dev.get("max_input_channels", 0) <= 0:
                continue
            if dev.get("name", "") == monitor_name:
                return monitor_name

    return None


def _find_mic_via_sounddevice(keyword: str) -> Optional[str]:
    """Cerca un dispositivo di input tramite la lista dispositivi sounddevice.

    Args:
        keyword: Parola chiave da cercare nel nome del dispositivo.

    Returns:
        Nome del dispositivo trovato, o None.
    """
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Errore query sounddevice: %s", exc)
        return None

    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        if keyword.lower() in name.lower():
            return name

    default_input = sd.default.device[0]
    if (default_input is not None and default_input >= 0
            and default_input < len(devices)):
        default_name = devices[default_input].get("name", "")
        logger.info("Microfono keyword non trovato, uso input predefinito: %s",
                     default_name)
        return default_name

    return None


def _find_via_pactl(keyword: str) -> Optional[str]:
    """Usa pactl per trovare il sink su cui Firefox riproduce.

    Args:
        keyword: Parola chiave per identificare Firefox.

    Returns:
        Nome del monitor source, o None.
    """
    try:
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        sink_inputs = result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("pactl sink-inputs non disponibile: %s", exc)
        return None

    firefox_sink_idx = extract_sink_index(sink_inputs, keyword)
    if firefox_sink_idx is None:
        return None

    sink_name = get_sink_name(firefox_sink_idx)
    if not sink_name:
        return None

    monitor_name = sink_name + ".monitor"
    try:
        devices = sd.query_devices()
        for dev in devices:
            if dev.get("max_input_channels", 0) > 0 and dev.get("name", "") == monitor_name:
                return monitor_name
    except Exception as exc:
        logger.debug("Errore verifica monitor in sounddevice: %s", exc)

    return monitor_name


def debug_dump() -> str:
    """Dump di tutte le informazioni sui dispositivi audio per il debug.

    Returns:
        Stringa formattata con tutte le informazioni audio.
    """
    lines: list[str] = []
    lines.append("=== sounddevice devices (input only) ===")
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                lines.append(f"  [{i}] {dev.get('name', '?')}")
                lines.append(f"      channels={dev.get('max_input_channels')} "
                             f"rate={dev.get('default_samplerate')}")
    except Exception as exc:
        lines.append(f"  Errore: {exc}")

    lines.append("")
    lines.append("=== pactl sources (monitors only) ===")
    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            if ".monitor" in line:
                lines.append(f"  {line}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        lines.append(f"  Errore: {exc}")

    return "\n".join(lines)
