# core/sink_finder.py
"""Discovery unificato dei dispositivi audio PipeWire / PulseAudio."""

from __future__ import annotations

import logging
from typing import Optional

import sounddevice as sd

from config.settings import AudioSource, Settings
from core.pactl import PactlRunner
from core.sink_helpers import hostapi_name

logger = logging.getLogger(__name__)


def find_source(
    settings: Settings | None = None,
    audio_source: Optional[str] = None,
    *,
    pactl_runner: Optional[PactlRunner] = None,
) -> Optional[str]:
    """Trova il dispositivo audio per ``system`` o ``microphone``."""
    if settings is None:
        settings = Settings()
    source = audio_source or settings.audio_source

    if source == AudioSource.SYSTEM.value:
        return find_system_monitor(pactl_runner=pactl_runner)
    if source == AudioSource.MICROPHONE.value:
        return find_microphone(settings)
    logger.warning("Sorgente audio sconosciuta: %s", source)
    return None


def find_system_monitor(*, pactl_runner: Optional[PactlRunner] = None) -> Optional[str]:
    """Trova il monitor dell'uscita audio predefinita."""
    runner = pactl_runner or PactlRunner()
    owns_runner = pactl_runner is None
    try:
        result = _find_default_monitor_via_pactl(runner)
        if result:
            logger.info("Monitor audio di sistema trovato via pactl: %s", result)
            return result
    finally:
        if owns_runner:
            runner.close()

    result = _find_default_monitor_via_sounddevice()
    if result:
        logger.info("Monitor audio di sistema trovato via sounddevice: %s", result)
        return result

    logger.warning("Impossibile individuare il monitor dell'uscita predefinita")
    return None


def find_firefox_sink(settings: Settings | None = None) -> Optional[str]:
    """Alias legacy: dalla v5.3 Firefox è sostituito dall'audio di sistema."""
    del settings
    return find_system_monitor()


def find_microphone(settings: Settings | None = None) -> Optional[str]:
    """Trova il microfono, preferendo un override keyword se configurato."""
    if settings is None:
        settings = Settings()
    keyword = str(settings.sink_search_keyword or "").strip()

    result = _find_mic_via_sounddevice(keyword)
    if result:
        logger.info("Microfono trovato via sounddevice: %s", result)
        return result

    logger.warning("Impossibile trovare il microfono con nessun metodo")
    return None


def list_available_devices() -> list[dict]:
    """Elenca tutti gli input, distinguendo monitor e microfoni."""
    devices = []
    try:
        device_list = sd.query_devices()
    except Exception as exc:
        logger.error("Impossibile interrogare i dispositivi: %s", exc)
        return []

    for i, dev in enumerate(device_list):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = str(dev.get("name", ""))
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
    """Restituisce soltanto le sorgenti monitor disponibili."""
    return [d for d in list_available_devices() if d["is_monitor"]]


def _default_sink_name_via_pactl(runner: PactlRunner) -> Optional[str]:
    output = runner.run(["get-default-sink"])
    if output:
        first = output.splitlines()[0].strip()
        if first:
            return first

    info = runner.run(["info"])
    if info:
        for line in info.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip().casefold() == "default sink":
                value = value.strip()
                if value:
                    return value
    return None


def _find_default_monitor_via_pactl(runner: PactlRunner) -> Optional[str]:
    sink_name = _default_sink_name_via_pactl(runner)
    if not sink_name:
        return None
    monitor_name = f"{sink_name}.monitor"

    sources = runner.run(["list", "short", "sources"])
    if sources:
        for line in sources.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == monitor_name:
                return monitor_name
        logger.debug("Monitor %s non presente in pactl sources", monitor_name)
        return None

    return monitor_name


def _find_default_monitor_via_sounddevice() -> Optional[str]:
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Errore query sounddevice: %s", exc)
        return None

    monitors = [
        str(dev.get("name", ""))
        for dev in devices
        if dev.get("max_input_channels", 0) > 0
        and (
            ".monitor" in str(dev.get("name", ""))
            or "monitor" in str(dev.get("name", "")).lower()
        )
    ]
    if not monitors:
        return None

    try:
        default_output = sd.default.device[1]
    except Exception:
        default_output = None
    if (
        default_output is not None
        and isinstance(default_output, int)
        and 0 <= default_output < len(devices)
    ):
        default_name = str(devices[default_output].get("name", ""))
        candidates = (
            f"{default_name}.monitor",
            default_name.removesuffix(".monitor") + ".monitor",
        )
        for candidate in candidates:
            if candidate in monitors:
                return candidate

    if len(monitors) == 1:
        return monitors[0]
    return None


def _find_mic_via_sounddevice(keyword: str = "") -> Optional[str]:
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Errore query sounddevice: %s", exc)
        return None

    if keyword:
        for dev in devices:
            if dev.get("max_input_channels", 0) <= 0:
                continue
            name = str(dev.get("name", ""))
            is_monitor = ".monitor" in name or "monitor" in name.lower()
            if not is_monitor and keyword.casefold() in name.casefold():
                return name

    try:
        default_input = sd.default.device[0]
    except Exception:
        default_input = None
    if (
        default_input is not None
        and isinstance(default_input, int)
        and 0 <= default_input < len(devices)
    ):
        dev = devices[default_input]
        if dev.get("max_input_channels", 0) > 0:
            default_name = str(dev.get("name", ""))
            if ".monitor" not in default_name and "monitor" not in default_name.lower():
                logger.info("Uso input predefinito: %s", default_name)
                return default_name

    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = str(dev.get("name", ""))
        if ".monitor" not in name and "monitor" not in name.lower():
            return name
    return None


def debug_dump(*, pactl_runner: Optional[PactlRunner] = None) -> str:
    """Dump delle informazioni audio utili al troubleshooting."""
    runner = pactl_runner or PactlRunner()
    owns_runner = pactl_runner is None
    try:
        lines: list[str] = []
        lines.append("=== default playback ===")
        lines.append(
            f"  default sink: {_default_sink_name_via_pactl(runner) or 'non disponibile'}"
        )
        lines.append(
            f"  system monitor: {find_system_monitor(pactl_runner=runner) or 'non disponibile'}"
        )

        lines.append("")
        lines.append("=== sounddevice devices (input only) ===")
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    lines.append(f"  [{i}] {dev.get('name', '?')}")
                    lines.append(
                        f"      channels={dev.get('max_input_channels')} "
                        f"rate={dev.get('default_samplerate')}"
                    )
        except Exception as exc:
            lines.append(f"  Errore: {exc}")

        lines.append("")
        lines.append("=== pactl sources (monitors) ===")
        sources = runner.run(["list", "short", "sources"])
        if sources is None:
            lines.append("  pactl non disponibile")
        else:
            found = False
            for line in sources.splitlines():
                if ".monitor" in line or "monitor" in line.lower():
                    lines.append(f"  {line}")
                    found = True
            if not found:
                lines.append("  nessun monitor")
        return "\n".join(lines)
    finally:
        if owns_runner:
            runner.close()
