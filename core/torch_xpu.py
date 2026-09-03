"""Shared PyTorch XPU runtime for Intel GPU inference.

This module is the single owner of PyTorch XPU device selection and validation.
Diarization and Demucs must obtain their compute device here instead of
implementing independent GPU detection or CPU fallbacks.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from config.constants import SYCLDefaults
from core.exceptions import GPUNotAvailableError

logger = logging.getLogger(__name__)


def _import_torch() -> Any:
    import torch

    return torch


class TorchXpuRuntime:
    """Validate once and expose the canonical PyTorch Intel XPU device."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._device: Any | None = None
        self._device_name = ""

    def require_device(self) -> Any:
        """Return ``torch.device('xpu:0')`` or raise an actionable error.

        A real tensor operation is executed before the device is accepted. This
        prevents package-only checks from reporting success when the Intel GPU
        runtime is missing or unusable.
        """
        with self._lock:
            if self._device is not None:
                return self._device

            os.environ.setdefault(
                "ONEAPI_DEVICE_SELECTOR",
                SYCLDefaults.ONEAPI_DEVICE_SELECTOR,
            )
            try:
                torch = _import_torch()
            except ImportError as exc:
                raise GPUNotAvailableError(
                    "PyTorch XPU non installato",
                    "Esegui ./install.sh per installare il runtime Intel XPU richiesto.",
                ) from exc

            xpu = getattr(torch, "xpu", None)
            if xpu is None or not callable(getattr(xpu, "is_available", None)):
                raise GPUNotAvailableError(
                    "PyTorch non espone il backend XPU",
                    "La build installata non è la wheel Intel XPU prevista da UltraTranscribr.",
                )
            if not xpu.is_available():
                raise GPUNotAvailableError(
                    "GPU Intel XPU non disponibile",
                    "Verifica Intel Compute Runtime/Level Zero e rilancia ./install.sh.",
                )
            try:
                count = int(xpu.device_count())
            except Exception as exc:
                raise GPUNotAvailableError(
                    "Impossibile interrogare i dispositivi XPU",
                    str(exc),
                ) from exc
            if count < 1:
                raise GPUNotAvailableError(
                    "Nessun dispositivo XPU rilevato",
                    "PyTorch XPU è installato ma non vede una GPU Intel utilizzabile.",
                )

            device = torch.device("xpu:0")
            try:
                probe = torch.ones((8, 8), dtype=torch.float32, device=device)
                value = (probe @ probe).sum().item()
                xpu.synchronize()
                if value <= 0:
                    raise RuntimeError("risultato probe XPU non valido")
            except Exception as exc:
                raise GPUNotAvailableError(
                    "Il probe PyTorch XPU è fallito",
                    str(exc),
                ) from exc

            try:
                name = str(xpu.get_device_name(0))
            except Exception:
                name = "Intel XPU"
            self._device = device
            self._device_name = name
            logger.info("PyTorch XPU pronto: %s", name)
            return device

    @property
    def device_name(self) -> str:
        if self._device is None:
            self.require_device()
        return self._device_name


_RUNTIME = TorchXpuRuntime()


def get_torch_xpu_device() -> Any:
    """Return the validated shared XPU device."""
    return _RUNTIME.require_device()


def probe_torch_xpu() -> tuple[bool, str]:
    """Return a non-throwing environment-check result."""
    try:
        _RUNTIME.require_device()
        return True, _RUNTIME.device_name
    except Exception as exc:
        return False, str(exc)
