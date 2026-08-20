# core/sink_helpers.py
"""Funzioni di utilità per il parsing dell'output di pactl.

Contiene gli helper di basso livello per il parsing dei blocchi
pactl e la risoluzione dei nomi dei sink. Separato da sink_finder.py
per rispettare il limite di 300 righe per file.

Functions:
    parse_pactl_blocks: Divide l'output lungo di pactl in blocchi.
    get_property_block: Estrae la sezione Properties da un blocco.
    find_line_starting: Trova una riga che inizia con un prefisso.
    extract_sink_index: Estrae l'indice del sink dallo output pactl.
    get_sink_name: Ottiene il nome del sink dal suo indice.
    hostapi_name: Restituisce un nome leggibile per l'host API.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def parse_pactl_blocks(output: str) -> list[str]:
    """Divide l'output lungo formato di pactl in blocchi per oggetto.

    Args:
        output: Output testuale di pactl.

    Returns:
        Lista di blocchi di testo, uno per oggetto.
    """
    blocks: list[str] = []
    current: list[str] = []

    for line in output.splitlines():
        if line and not line[0].isspace():
            if current:
                blocks.append("\n".join(current))
                current = []
            current.append(line)
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))
    return blocks


def get_property_block(block: str) -> Optional[str]:
    """Estrae la sezione Properties da un blocco pactl.

    Args:
        block: Blocco di testo di un oggetto pactl.

    Returns:
        Testo delle proprietà, o None.
    """
    in_props = False
    prop_lines: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("properties"):
            in_props = True
            continue
        if in_props:
            if stripped and not line[0].isspace():
                break
            if stripped:
                prop_lines.append(stripped)
    return "\n".join(prop_lines) if prop_lines else None


def find_line_starting(block: str, prefix: str) -> Optional[str]:
    """Trova una riga nel blocco che inizia con il prefisso dato.

    Args:
        block: Blocco di testo.
        prefix: Prefisso da cercare.

    Returns:
        La riga trovata, o None.
    """
    for line in block.splitlines():
        if line.strip().lower().startswith(prefix.lower()):
            return line
    return None


def extract_sink_index(sink_inputs: str, keyword: str) -> Optional[str]:
    """Estrae l'indice del sink dallo output di pactl list sink-inputs.

    Args:
        sink_inputs: Output di 'pactl list sink-inputs'.
        keyword: Parola chiave per identificare l'applicazione.

    Returns:
        Indice del sink come stringa, o None.
    """
    blocks = parse_pactl_blocks(sink_inputs)
    for block in blocks:
        props = get_property_block(block)
        if props and keyword.lower() in props.lower():
            sink_line = find_line_starting(block, "Sink:")
            if sink_line:
                try:
                    return sink_line.split(":")[1].strip()
                except (IndexError, ValueError):
                    pass
    return None


def get_sink_name(sink_index: str) -> Optional[str]:
    """Ottiene il nome del sink dal suo indice tramite pactl.

    Args:
        sink_index: Indice del sink come stringa.

    Returns:
        Nome del sink, o None.
    """
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] == sink_index:
            return parts[1]
    return None


def hostapi_name(hostapi_index: int) -> str:
    """Restituisce un nome leggibile per l'host API sounddevice.

    Args:
        hostapi_index: Indice dell'host API.

    Returns:
        Nome leggibile dell'host API.
    """
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        if 0 <= hostapi_index < len(apis):
            return apis[hostapi_index].get("name", f"API {hostapi_index}")
    except Exception as exc:
        logger.debug("Errore query hostapis: %s", exc)
    return f"API {hostapi_index}"
