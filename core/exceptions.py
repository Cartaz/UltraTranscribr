# core/exceptions.py
"""Gerarchia delle eccezioni personalizzate per UltraTranscribr.

Definisce una classe base AppError e sottoclassi per dominio.
Il livello core solleva eccezioni specifiche; il livello UI le
cattura e le presenta all'utente con messaggio localizzato.

Classes:
    AppError: Eccezione base dell'applicazione.
    SinkNotFoundError: Sink audio non trovato.
    GPUNotAvailableError: GPU Intel Arc / SYCL non disponibili.
"""

from __future__ import annotations


class AppError(Exception):
    """Eccezione base per tutti gli errori dell'applicazione.

    Attributes:
        message: Messaggio descrittivo dell'errore.
        detail: Dettaglio aggiuntivo opzionale.
    """

    def __init__(self, message: str, detail: str = "") -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)

    def __str__(self) -> str:
        """Mantiene il dettaglio operativo quando l'errore attraversa thread/UI."""
        if self.detail:
            return f"{self.message}\n{self.detail}"
        return self.message


class SinkNotFoundError(AppError):
    """Sink audio PipeWire/PulseAudio non trovato."""

    pass


class GPUNotAvailableError(AppError):
    """GPU Intel Arc o backend SYCL non disponibili.

    Sollevata quando il sistema non soddisfa i requisiti minimi
    per l'accelerazione GPU (driver Level Zero, Intel Compute
    Runtime, GPU Intel Arc rilevata).
    """

    pass
