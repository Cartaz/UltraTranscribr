"""Vocal isolation through Demucs on the shared Intel XPU runtime.

There is one supported inference path: ``demucs-infer`` + PyTorch XPU. Missing
packages or GPU/runtime failures are fatal for an explicitly requested vocal
isolation; UltraTranscribr never falls back silently to CPU or to the original
mixed track.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Callable, Optional

from core.torch_xpu import get_torch_xpu_device

logger = logging.getLogger(__name__)


def is_demucs_available() -> bool:
    """Require the single supported Demucs package.

    The historical boolean API is retained for the existing file worker, but a
    missing mandatory runtime is now an error instead of a signal to fall back
    to the original mixed audio.
    """
    if importlib.util.find_spec("demucs_infer") is None:
        raise RuntimeError("demucs-infer non installato; esegui ./install.sh")
    return True


def isolate_vocals(
    input_path: str,
    model_name: str = "htdemucs",
    device: str = "xpu",
    stop_event: Optional[object] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """Extract the vocal stem on Intel XPU and return its temporary WAV path."""
    is_demucs_available()
    # Device selection is no longer a caller concern. Keep the argument only
    # for compatibility with the current worker API and always use shared XPU.
    if str(device).lower() != "xpu":
        logger.debug("Ignoro device Demucs legacy %r: XPU è obbligatorio", device)

    input_file = Path(input_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"File non trovato: {input_path}")

    xpu_device = get_torch_xpu_device()
    logger.info(
        "Isolamento vocale Demucs — modello: %s, device: %s",
        model_name,
        xpu_device,
    )
    if progress_callback:
        progress_callback(0)

    from core.vocal_isolator_io import isolate_vocals_xpu

    return isolate_vocals_xpu(
        str(input_file),
        model_name,
        xpu_device,
        stop_event,
        progress_callback,
    )


def cleanup_vocals(vocal_path: Optional[str]) -> None:
    """Remove the temporary vocal stem and its private directory."""
    if not vocal_path:
        return
    try:
        path = Path(vocal_path)
        if path.exists():
            path.unlink()
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError as exc:
        logger.warning("Impossibile rimuovere il file vocale temporaneo: %s", exc)
