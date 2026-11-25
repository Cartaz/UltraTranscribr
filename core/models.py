# core/models.py
"""Modelli dati per UltraTranscribr.

Definisce i modelli come dataclass e enum utilizzati da tutti i livelli
dell'applicazione. Indipendenti da Qt e dall'interfaccia utente.

Classes:
    StatusEnum: Codici di stato dell'applicazione.
"""

from __future__ import annotations

from enum import Enum


class StatusEnum(str, Enum):
    """Codici di stato dell'applicazione / trascrizione."""

    IDLE = "idle"
    RUNNING = "running"
    BUFFERING = "buffering"
    ERROR = "error"
    LOADING_MODEL = "loading_model"
    ISOLATING_VOCALS = "isolating_vocals"
    STOPPED = "stopped"
    COMPLETED = "completed"

