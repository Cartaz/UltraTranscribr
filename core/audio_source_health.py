"""Pure audio-source availability evaluation for UI and tests."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from config.settings import AudioSource


def evaluate_audio_source_health(
    *,
    source: str,
    selection: str = "",
    devices: Iterable[dict[str, Any]] = (),
    streams: Iterable[dict[str, Any]] = (),
    automatic_source: Optional[str] = None,
) -> dict[str, Any]:
    """Build a presentation-neutral availability snapshot.

    Discovery is intentionally performed by the caller. Keeping this function
    pure lets the same status semantics be exercised in headless CI without
    importing QtWebEngine or talking to PipeWire/PulseAudio.
    """
    selected_input = str(selection or "").strip()

    if source == AudioSource.APPLICATION.value:
        stream_list = list(streams)
        if selected_input:
            try:
                stream_id = int(selected_input)
            except ValueError:
                stream_id = -1
            selected = next(
                (
                    item
                    for item in stream_list
                    if int(item.get("id", -1)) == stream_id
                ),
                None,
            )
            if selected is None:
                return {
                    "source": source,
                    "status": "disconnected",
                    "label": "Stream disconnesso",
                    "detail": "Lo stream selezionato non è più presente.",
                    "streams": len(stream_list),
                }
            playing = str(selected.get("state") or "").casefold() != "paused"
            return {
                "source": source,
                "status": "playing" if playing else "available",
                "label": (
                    "In riproduzione"
                    if playing
                    else "Disponibile · in pausa"
                ),
                "detail": (
                    selected.get("display_name")
                    or f"Stream #{stream_id}"
                ),
                "stream": selected,
                "streams": len(stream_list),
            }
        if stream_list:
            return {
                "source": source,
                "status": "available",
                "label": f"Disponibili {len(stream_list)} stream",
                "detail": "Seleziona lo stream da isolare.",
                "streams": len(stream_list),
            }
        return {
            "source": source,
            "status": "disconnected",
            "label": "Nessuno stream",
            "detail": (
                "Avvia la riproduzione in un'applicazione e aggiorna l'elenco."
            ),
            "streams": 0,
        }

    device_list = list(devices)
    key = "is_monitor" if source == AudioSource.SYSTEM.value else "is_mic"
    candidates = [item for item in device_list if bool(item.get(key))]
    if selected_input:
        selected = next(
            (
                item
                for item in candidates
                if str(item.get("name") or "") == selected_input
            ),
            None,
        )
        if selected is None:
            return {
                "source": source,
                "status": "disconnected",
                "label": "Dispositivo non disponibile",
                "detail": selected_input,
                "devices": len(candidates),
            }
        return {
            "source": source,
            "status": "available",
            "label": "Disponibile",
            "detail": str(selected.get("name") or selected_input),
            "device": selected,
            "devices": len(candidates),
        }

    if automatic_source:
        return {
            "source": source,
            "status": "available",
            "label": "Disponibile · automatico",
            "detail": str(automatic_source),
            "devices": len(candidates),
        }

    label = (
        "Audio di sistema non disponibile"
        if source == AudioSource.SYSTEM.value
        else "Microfono non disponibile"
    )
    return {
        "source": source,
        "status": "disconnected",
        "label": label,
        "detail": "Nessun ingresso compatibile rilevato.",
        "devices": len(candidates),
    }
